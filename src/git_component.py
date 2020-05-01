#!/usr/bin/env python3
"""
Copyright (C) Smartsoftdev.eu SRL - All Rights Reserved
For any license violations please contact: SmartSoftDev.eu

This app computes and unique hash of an component located in a git repository,in multiple locations (files,
directories). Then it saves the installed hash and information into storage file. So when running the script next time
a changelog, and update mechanism.

Use cases:
* This is specially useful when in the repo there are multiple components and we have to detect if one component
changed with this commit.
* Another useful case is when changes in specific files/directories (like documentation, helper scripts, etc) must not
trigger deployment or building of the component.

The app receives a list of paths (or a yaml file with path list) and then gets the git hash of those locations and at
the end it computes one hash from the one's from git and returns it.
NOTE: Git returns the hash FROM committed changes not for stashed once! so make sure when running
git_component_hash that you do not have local changes in the git repositories.

To ease automation the app will look to .git_component.yml file in current directory.

config file format:
locations:
  - relative/path/directory1
  - relative/path2/file1
name: AppName
install-scripts: # list of scripts to run when the component needs installation
  - bash script
update-script:  # list of scripts to run when the component needs update
  - bash script

NOTE: if you have ideas how to improve this script just create an issue on https://github.com/SmartSoftDev/GBashLib
"""
import sys
import os
import datetime
import argparse
import subprocess
import hashlib
import yaml
import re

from timeit import default_timer as timer


def slugify(text):
    return re.sub(r'[\W_]+', '-', text)


def args_parse():
    parser = argparse.ArgumentParser(
        description='Compute a hash of multiple git locations')
    parser.add_argument('-v', '--debug', action='count',
                        default=0, help='Enable debugging')
    parser.add_argument('-c', '--config', action='store', type=str, default=None,
                        help='Path to the yaml config file, or directory where .git_component.yml (default=.)')
    parser.add_argument('-l', '--limit', action='store', type=int, default=65,
                        help='limit the size of hash (default=65)')
    parser.add_argument('-i', '--install-check', action='store_true', default=None,
                        help='Run component install scripts if it was not installed before')
    parser.add_argument('-u', '--update-check', action='store_true', default=None,
                        help='Run component update scripts if it is detected that the component changed')
    parser.add_argument('-C', '--changelog', action='store_true', default=None,
                        help='Generate changelog from git history.')
    parser.add_argument('-f', '--from-commit', action='store', type=str, default=None,
                        help='Changelog from this commit. '
                             'Commit hash or list of git-remote-url!commit-hash,git-remote-url!commit-hash,... ')
    parser.add_argument('-s', '--store-path', action='store', type=str, default=None,
                        help='path to the directory to store current installation status for the components '
                        '(default=/etc/_git_components/')
    parser.add_argument('--user', action='store_true', default=None,
                        help='sets path to installation status store to $HOME/.git_components/')

    return parser.parse_args()


class GitComponent:
    class GitComponentException(Exception):
        pass

    DEF_CMP_FILE_NAME = '.git_component.yml'
    DEF_GLOBAL_STORE_DIR = '/etc/_git_components/'
    DEF_USER_STORE_DIR = '.git_components/'
    CHANGELOG_FILE_NAME = '{cmp_name_slug}_changelog.yml'

    def _get_repo_hash(self, locations):
        repos = dict()
        for loc in locations:
            loc = os.path.join(self.cwd, loc)
            if os.path.isfile(loc):
                repo_cwd = os.path.dirname(loc)
            else:
                repo_cwd = loc
            cmd = ["git", "ls-remote", "--get-url"]
            resp = subprocess.check_output(cmd, cwd=repo_cwd).decode("utf-8").strip()
            if len(resp) == 0:
                raise self.GitComponentException(f"Could not get git remote repo from {loc}, is it under git control?")
            repo = resp
            if repo not in repos:
                cmd = ["git", "log", "-n1", "--format=%H", '--', loc]
                resp = subprocess.check_output(cmd, cwd=repo_cwd).decode("utf-8").strip()
                if len(resp) == 0:
                    raise self.GitComponentException(
                        f"Could not get git commit for the repo from {loc}, is it under git control?")
                repo_hash = resp
                repos[repo] = repo_hash
        return repos

    def _run_scripts(self, scripts):
        i = 0
        res = 0
        res_ret_code = 0
        start_time = timer()
        for script in scripts:
            i += 1
            print(f"Running {i} of {len(scripts)}: {script!r} =====================================")
            sys.stdout.flush()
            script_res = subprocess.run(script, shell=True, cwd=self.cwd)
            print("=====================================")
            sys.stdout.flush()
            if script_res.returncode != 0:
                print(f"Error: returncode={script_res.returncode} when running {script!r}")
                res = script_res.returncode
                break
        end_time = timer()
        return res, round(end_time-start_time, 3)

    def _recursive_dict_update(self, d, u):
        for k, v in u.items():
            if isinstance(v, dict):
                d[k] = self._recursive_dict_update(d.get(k, {}), v)
            else:
                d[k] = v
        return d

    def _save_installation_info(self, cmp_file_path,
                                final_hash, repos, location, inst_duration, update=False, old_info=None):
        inst_time = datetime.datetime.utcnow()
        inst_epoch = round(inst_time.timestamp(), 3)
        info = {
            "current_version": {
                "hash": final_hash,
                "repos": repos,
                "utctime": inst_time,
                "utcepoch": inst_epoch,
                "location": location,
                "duration": inst_duration,
            }
        }

        if update:
            info['previous_version'] = old_info['current_version'].copy()
        else:
            info['first_version'] = info['current_version'].copy()

        if old_info:
            new_info = old_info.copy()
            info = self._recursive_dict_update(new_info, info)

        with open(cmp_file_path, "w+") as f:
            yaml.safe_dump(info, f)
        print(f"{'Update' if update else 'Installation'} info saved in {cmp_file_path}")
        return info

    @staticmethod
    def _load_installation_info(cmp_file_path):
        info = None
        if os.path.exists(cmp_file_path):
            # this component was installed
            with open(cmp_file_path, "r") as f:
                info = yaml.safe_load(f)
        return info

    @staticmethod
    def _parse_commits(txt):
        res = []
        commits = txt.split("_#._")
        for commit in commits:
            commit = commit.strip()
            if len(commit) == 0:
                continue
            commit = commit.split("|$.|", maxsplit=4)
            res.append({
                "hash": commit[0].strip(),
                "author": commit[1].strip(),
                "time": commit[2].strip(),
                "subject": commit[3].strip(),
                "body": commit[4].strip()
            })
        return res

    def __init__(self, args):
        self.args = args
        cfg_file = self.DEF_CMP_FILE_NAME
        if self.args.config:
            if os.path.isdir(self.args.config):
                cfg_file = os.path.join(self.args.config, self.DEF_CMP_FILE_NAME)
            else:
                cfg_file = self.args.config
        if not os.path.exists(cfg_file):
            raise self.GitComponentException('Config file %r NOT found!', cfg_file)
        self.cwd = os.path.realpath(os.path.dirname(cfg_file))
        self.real_cfg_file = os.path.realpath(cfg_file)
        with open(cfg_file, "r") as f:
            self.file = yaml.safe_load(f)
        self.is_just_installed = False
        self.is_just_updated = False

    def _debug(self, txt):
        if self.args.debug:
            print(txt)

    def run(self):

        locations = self.file.get("locations")
        if not locations:
            raise self.GitComponentException("Config file has no 'locations' list!")
        if not isinstance(locations, list):
            raise self.GitComponentException("'locations' field from config file MUST be a list!")

        self._debug(f"git-hashes:")
        cmp_name = self.file.get("name")
        if not cmp_name:
            raise self.GitComponentException("'name' field is missing")
        # we need to need to check the install or/and update scripts
        store_dir = '/etc/_git_components/'
        if self.args.user:
            store_dir = os.path.join(os.getenv('HOME'), ".git_components")
        if self.args.store_path:
            store_dir = self.args.store_path
        if not os.path.exists(store_dir):
            os.makedirs(store_dir)
        cmp_name_slug = slugify(cmp_name)
        cmp_file_name = os.path.join(store_dir, f"{cmp_name_slug}.yml")
        for loc in locations:
            if not isinstance(loc, (int, float, str)):
                raise self.GitComponentException(f"location={loc} is not a string!")
            try:
                loc = str(loc)
            except Exception:
                raise self.GitComponentException(f"location={loc} is not a string!")
            if os.path.isabs(loc):
                raise self.GitComponentException(
                    f"location={loc} is ABSOLUTE (only relative paths are allowed)")

        # we MUST always sort the locations so that the result does not change when the order is different
        locations = sorted(locations)
        hashes = []
        for loc in locations:
            loc = os.path.join(self.cwd, loc)
            cmd = ["git", "log", "-n1", '--format=%H', "--", loc]
            resp = subprocess.check_output(cmd, cwd=self.cwd).decode("utf-8").strip()
            if len(resp) == 0:
                raise self.GitComponentException(f"Could not get git has from {loc}, is it under git control?")
            self._debug(f"\t{loc} {resp!s}")
            hashes.append(resp)
        final_hash = None
        if len(hashes) == 0:
            raise self.GitComponentException("There are no valid locations to get the hash")
        elif len(hashes) == 1:
            final_hash = hashes[0]
        else:
            hasher = hashlib.sha256()
            for line in hashes:
                hasher.update(line.encode('utf-8'))
            final_hash = hasher.hexdigest()
        print(final_hash[:self.args.limit])

        info = self._load_installation_info(cmp_file_name)

        if self.args.install_check and not info:
            # we must run first the install, only then changelog
            print(f"component {cmp_name} must be installed ...")
            repos = self._get_repo_hash(locations)
            for repo, repo_hash in repos.items():
                print(f"Repo={repo} with repo_commit={repo_hash}")

            inst_scripts = self.file.get("install-scripts", [])
            if not inst_scripts or len(inst_scripts) == 0:
                print("Nothing to run: install-scripts is empty or missing")
            else:
                scripts_res, install_duration = self._run_scripts(inst_scripts)
                print(f"Installation of component={cmp_name!r} has {'succeeded' if scripts_res == 0 else 'FAILED'}")
                if scripts_res == 0:
                    info = self._save_installation_info(
                        cmp_file_name,
                        final_hash,
                        repos,
                        self.real_cfg_file,
                        install_duration
                    )
                    self.is_just_installed = True
                else:
                    return scripts_res

        if self.args.update_check and info and not self.is_just_installed:
            if info['current_version']['hash'] == final_hash:
                print(f"Component {cmp_name!r} is up to date ...")
            else:
                print(f"Component {cmp_name!r} must be updated ...")
                repos = self._get_repo_hash(locations)
                for repo, repo_hash in repos.items():
                    print(f"Repo={repo} with "
                          f"repo_commit={info['current_version']['repos'].get(repo,'')[:8]} -> {repo_hash[:8]}")
                update_scripts = self.file.get("update-scripts", [])
                scripts_res, scripts_duration = self._run_scripts(update_scripts)
                print(f"Update of component={cmp_name!r} has {'succeeded' if scripts_res == 0 else 'FAILED'}")
                if scripts_res == 0:
                    info = self._save_installation_info(
                        cmp_file_name,
                        final_hash,
                        repos,
                        self.real_cfg_file,
                        scripts_duration,
                        True,
                        info
                    )
                    self.is_just_updated = True
                else:
                    return scripts_res
        if self.args.changelog and (self.is_just_installed or self.is_just_updated):
            # Changelog must be executed before updating to the newest version
            cmp_changelog_file_path = os.path.join(store_dir, f"{cmp_name_slug}_changelog.yml")
            if os.path.exists(cmp_changelog_file_path):
                with open(cmp_changelog_file_path, "r") as f:
                    old_changelog_info = yaml.safe_load(f)
            else:
                old_changelog_info = {
                    "history": []
                }
            if len(old_changelog_info['history']) > 0 and old_changelog_info['history'][0]['hash'] == final_hash:
                print(f"The changelog for {cmp_name} was already generated ...")
            else:
                print(f"Generate changelog ... ")
                if info.get('first_version', dict()).get('hash') == final_hash:
                    # this means it is first install
                    # we need to reset the changelog
                    old_changelog_info = {
                        "history": []
                    }
                    print(f"First install detected, computing all commits on the component ...")
                    repos = {}
                else:
                    repos = info['previous_version']['repos']

                changelog = {}
                unique_commit_hash = []
                for loc in locations:
                    loc = os.path.join(self.cwd, loc)
                    if os.path.isfile(loc):
                        repo_cwd = os.path.dirname(loc)
                    else:
                        repo_cwd = loc
                    cmd = ["git", "ls-remote", "--get-url"]
                    resp = subprocess.check_output(cmd, cwd=repo_cwd).decode("utf-8").strip()
                    if len(resp) == 0:
                        raise self.GitComponentException(f"Could not get git remote repo from {loc},"
                                                         f" is it under git control?")
                    repo = resp
                    loc = os.path.join(self.cwd, loc)
                    cmd = ["git", "log", '--format=_#._%H|$.|%aN|$.|%aI|$.|%s|$.|%b']
                    if repo in repos:
                        cmd.append(f"{repos[repo]}..HEAD")
                    cmd += ["--", loc]

                    resp = subprocess.check_output(cmd, cwd=repo_cwd).decode("utf-8").strip()
                    commits = self._parse_commits(resp)
                    print(f"Got {len(commits)} commits")
                    for commit in commits:
                        hash = commit.get("hash")
                        if hash in unique_commit_hash:
                            continue  # already added
                        unique_commit_hash.append(hash)
                        if repo not in changelog:
                            changelog[repo] = []
                        changelog[repo].append(commit)
                new_changelog_info = {
                    "hash": final_hash,
                    "utcepoch": info['current_version']['utcepoch'],
                    "utctime": info['current_version']['utctime'],
                    "changelog": changelog,
                    "repos": info['current_version']['repos'],
                    "location": cmp_file_name
                }
                old_changelog_info['history'].insert(0, new_changelog_info)
                with open(cmp_changelog_file_path, "w+") as f:
                    yaml.safe_dump(old_changelog_info, f)


        return 0


if __name__ == "__main__":
    sys.exit(GitComponent(args_parse()).run())
