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
name: AppName
git_tag_prefix: tag prefix to look for latest version, default ""
location_root:  from where to start to copy locations
locations:
  - relative/path/directory1
  - relative/path2/file1
package-storage: path to the directory to store newly generated packages (relative or absolute)
package-archive-type: tgz or zip
package-info: a json object written to the package info.json file
package-actions:
  install: path_to_install_script
  update: path_to_update_script
  uninstall: path_uninstall_script
  other_action: path_to_other_action

# Bash commands lists
# for example
install-scripts: # list of scripts to run when the component needs installation
  - bash commands
update-script:  # list of scripts to run when the component needs update
  - bash commands
update-dependencies-scripts:  # list of scripts to run when the component needs update
  run_on_change:
    - be/requirement.pep3
    - fe_ui/package.json
    - fe_prm/package.json
  run:
    - bash commands


NOTE: if you have ideas how to improve this script just create an issue on https://github.com/SmartSoftDev/GBashLib

# Run commands examples:

git_component run_on_change -C update-scripts unittes-scripts ...
git_component run_on_change -C update-dependencies-scripts
git_component get_changelog -o destination_file.yml

# usefull find last version of deb file
find . -type f -name 'crm_*.deb' | sort -r -V  | head -n1
"""
import argparse
import datetime
import hashlib
import os
import shutil
import subprocess
import sys
from timeit import default_timer as timer
from typing import List

import yaml

from utils import slugify, write_cfg_file, compose_build_commit_hash, get_last_tag, gen_random_hash

CHECKSUM_CHUNK_SIZE = 4096


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
    parser.add_argument('-F', '--check-changes-from-commit', action='store', type=str, default=None,
                        help='It will check if from that commit are changes.')
    parser.add_argument('-s', '--store-path', action='store', type=str, default=None,
                        help='path to the directory to store current installation status for the components '
                             '(default=/etc/_git_components/)')
    parser.add_argument('--user', action='store_true', default=None,
                        help='sets path to installation status store to $HOME/.git_components/')

    subparsers = parser.add_subparsers(title="Sub commands")
    sp = subparsers.add_parser("run_tests", help="Run tests.")
    sp.set_defaults(cmd="run_tests")
    sp.add_argument('-U', '--unittest-check', action='store_true', default=None,
                    help='Run component unittest scripts before installing or updating.')
    sp.add_argument('-I', '--integration-check', action='store_true', default=None,
                    help='Run component integration scripts after installing or updating')
    sp.add_argument('-E', '--e2e-check', action='store_true', default=None,
                    help='Run component end to end scripts after installing or updating')

    sp = subparsers.add_parser("pack", help="Create install package.")
    sp.set_defaults(cmd="pack")
    sp.add_argument('-s', '--store-path', action='store', type=str, default=None,
                    help='path to the directory to create new package (default=/tmp/gig-randomHash), or package-store '
                         'field from .git_component.yml')
    sp.add_argument('-t', '--package_type', type=str, choices=['tgz', 'zip', 'deb', 'none'],
                    help='Creates package of type (deletes package storage directory)(overrides the cfg file entry).')
    sp.add_argument('-S', '--package_storage', type=str,
                    help='Path to store the archives or packages (overrides the cfg file entry).')
    sp.add_argument('-k', '--keep-storage-dir', action='store_true', default=None,
                    help='Keep storage directory even if archive package was chosen')

    return parser.parse_args()


def create_deb_package(gc, info, package_name, root_dir):
    package_file = f"{package_name}.deb"
    debian_dir = os.path.join(root_dir, "DEBIAN")
    os.makedirs(debian_dir, exist_ok=True)
    os.chdir(debian_dir)
    with open('control', 'w+') as f:
        for k, v in gc.file.items():
            if k.startswith("deb-"):
                f.write(f"{k[4:]}: {v.strip()}\n")
        f.write(f"Version: {info.get('version')}\n")
        f.write(f"Package: {gc.name}\n")

    os.chdir(os.path.dirname(root_dir))
    subprocess.check_output(f"dpkg-deb --build {root_dir}", shell=True)
    return package_file


def compute_check_sums(_file):
    with open(_file, mode="rb", buffering=0) as fp:
        md5_hash_func = hashlib.md5()
        sha256_hash_func = hashlib.sha256()
        buffer = fp.read(CHECKSUM_CHUNK_SIZE)
        while len(buffer) > 0:
            md5_hash_func.update(buffer)
            sha256_hash_func.update(buffer)
            buffer = fp.read(CHECKSUM_CHUNK_SIZE)
    return sha256_hash_func.digest().hex(), md5_hash_func.digest().hex()


def create_package(gc, info: dict, _package_type: str, _src_dir: str, keep_storage_dir: bool) -> None:
    package_name = os.path.basename(_src_dir)
    root_dir = os.path.dirname(_src_dir)
    base_dir = os.path.relpath(_src_dir, root_dir)
    os.chdir(root_dir)
    if _package_type == "tgz":
        package_file = shutil.make_archive(package_name, 'gztar', root_dir=root_dir, base_dir=base_dir)
    elif _package_type == "zip":
        package_file = shutil.make_archive(package_name, 'zip', root_dir=root_dir, base_dir=base_dir)
    elif _package_type == "deb":
        package_file = create_deb_package(gc, info, package_name, _src_dir)
    else:
        raise NotImplementedError()
    sha256_check_sum, md5_check_sum = compute_check_sums(package_file)
    info.update({"sha256sum": sha256_check_sum,
                 "md5sum": md5_check_sum,
                 "file_name": os.path.basename(package_file),
                 "package_type": _package_type
                 })
    write_cfg_file(os.path.join(root_dir, f"{package_file}.info.json"), info, human_readable=True)
    if not keep_storage_dir:
        shutil.rmtree(_src_dir)


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
            loc = os.path.join(self.abs_location_root, loc)
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
        res = 0
        start_time = timer()
        for i, script in enumerate(scripts, 1):
            print(f"Running {i} of {len(scripts)}: {script!r}")
            sys.stdout.flush()
            script_res = subprocess.run(script, shell=True, cwd=self.cwd)
            print(f"End of {len(scripts)}: {script!r} <-------------------")
            sys.stdout.flush()
            if script_res.returncode != 0:
                print(f"Error: return code={script_res.returncode} when running {script!r}")
                res = script_res.returncode
                break
        end_time = timer()
        return res, round(end_time - start_time, 3)

    def _recursive_dict_update(self, d, u):
        for k, v in u.items():
            if isinstance(v, dict):
                d[k] = self._recursive_dict_update(d.get(k, {}), v)
            else:
                d[k] = v
        return d

    def _save_installation_info(self, cmp_file_path,
                                final_hash, location, inst_duration, update=False, old_info=None):
        inst_time = datetime.datetime.utcnow()
        inst_epoch = round(inst_time.timestamp(), 3)
        info = {
            "current_version": {
                "hash": final_hash,
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

    def __get_location_list(self, field):
        component_field = self.file.get(field, [])
        ret = []
        for el in component_field:
            if not isinstance(el, (int, float, str)):
                raise self.GitComponentException(f"'{field}' must be string")
            el = str(el)
            if not el:
                raise self.GitComponentException(f"'{field}' contains empty strings")
            ret.append(el)

        return ret

    def __get_location_object_list(self, field):
        component_field = self.file.get(field, [])
        if component_field is None:
            raise self.GitComponentException(f"Config file has no '{field}' list!")
        if not isinstance(component_field, list):
            raise self.GitComponentException(f"'{field}' field from config file MUST be a list!")
        for el in component_field:
            if isinstance(el, dict):
                if not (el.get("src") and el.get("dst")) and not (len(el.get("src")) and len(el.get("dst"))):
                    raise self.GitComponentException(f"'{field}' must contain list of str or dict with non empty "
                                                     f"src' and 'dst' keys")
            elif isinstance(el, (int, float, str)):
                if not len(el):
                    raise self.GitComponentException(f"'{field}' contains empty strings")
            else:
                raise self.GitComponentException(f"'{field}' must contain list of str or dict with non empty "
                                                 f"'src' and 'dst' keys")
        path_list = [el.get("src") if isinstance(el, dict) else el for el in component_field]
        return path_list, component_field

    def __get_paths_to_git_check(self):
        # deduplicate
        build_commit_hash_file_list = []
        for fpath in self.all_git_files_to_look:
            fpath = os.path.relpath(os.path.abspath(os.path.join(self.abs_location_root, fpath)), self.abs_location_root)
            if fpath.startswith("../"):
                raise Exception(f"'{fpath}' outside root location")
            if fpath not in build_commit_hash_file_list:
                build_commit_hash_file_list.append(fpath)

        self._debug(f"check build commit hash on files: {build_commit_hash_file_list}")
        for fpath in build_commit_hash_file_list:
            check_path = os.path.join(self.abs_location_root, fpath)
            if not os.path.islink(check_path) and not os.path.exists(check_path):
                raise Exception(f"File does not exist: {os.path.join(self.abs_location_root, fpath)}")

        return build_commit_hash_file_list
    def __get_git_version(self):
        prefix = self.file.get("git_tab_prefix", "")
        last_tag = get_last_tag(self.cwd, _filter=f"{prefix}*")  # for git list we need glob *

        build_commit_hash = compose_build_commit_hash(self.abs_location_root,
                                                        last_tag,
                                                        self.__get_paths_to_git_check(),
                                                        self.args.limit)
        return f"{last_tag or '0.0.1'}{build_commit_hash}"
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
        self.cwd = os.path.abspath(os.path.dirname(cfg_file))
        self.real_cfg_file = os.path.abspath(cfg_file)
        with open(cfg_file, "r") as f:
            self.file = yaml.safe_load(f)
        self.is_just_installed = False
        self.is_just_updated = False
        self.name = None
        self.destination_root = ""
        self.location_root = None

    def _debug(self, txt):
        if self.args.debug:
            print(txt)

    def get_root_location(self):
        self.location_root = self.file.get("location_root")
        if self.location_root and not isinstance(self.location_root, str):
            self.destination_root = self.location_root.get("dst")
            self.location_root = self.location_root.get("src")

        if not self.location_root:
            self.location_root = self.cwd
        if os.path.isabs(self.location_root):
            self.abs_location_root = self.location_root
        else:
            self.abs_location_root = os.path.abspath(os.path.join(self.cwd, self.location_root))
        self._debug(f"location root: {self.abs_location_root}")


    def process_cmds(self):
        cmd = getattr(self.args, 'cmd', None)
        if cmd:
            if cmd == "run_tests":
                for tests_type in ["unittest", "integration", "e2e"]:
                    if getattr(self.args, f"{tests_type}_check"):
                        inst_scripts = self.file.get(f"{tests_type}-scripts", [])
                        if not inst_scripts or len(inst_scripts) == 0:
                            print(f"Nothing to run for {self.name}: {tests_type}-scripts is empty or missing")
                        else:
                            scripts_res, install_duration = self._run_scripts(inst_scripts)
                            print(f"{tests_type.capitalize()} of component={self.name!r} has "
                                  f"{'succeeded' if scripts_res == 0 else 'FAILED'}")
                            if scripts_res != 0:
                                return scripts_res
            elif cmd == "pack":
                if not self.file.get("package"):
                    print("No packaging device ... nothing to do")
                    return

                # first check if scripts was run with package_storage argument if not
                # load it from file
                store_dir = self.args.package_storage

                if not store_dir:
                    store_dir = self.file.get("package-storage", None)

                if store_dir:
                    if not os.path.isabs(store_dir):
                        store_dir = os.path.abspath(os.path.join(self.cwd, store_dir))
                else:
                    store_dir = f'/tmp/gig_{gen_random_hash()}'
                if self.args.store_path:
                    store_dir = os.path.abspath(self.args.store_path)
                if not os.path.exists(store_dir):
                    os.makedirs(store_dir)
                self._debug(f"package tmp dir:{store_dir}")
                package_version = self.__get_git_version()
                package_label = f"{slugify(self.name)}_{package_version}"
                arch_type = self.args.package_type
                if not arch_type:
                    arch_type = self.file.get("package-archive-type")
                if arch_type == 'none':
                    arch_type = None

                self._debug(f"package name:{package_label}")
                package_dir = os.path.join(store_dir, package_label)
                # let's check if the version already exists
                if arch_type:
                    if arch_type == 'tgz':
                        file_extension = f'{package_dir}.tar.gz'
                    elif arch_type == 'deb':
                        file_extension = f'{package_dir}.deb'
                    else:
                        file_extension = f'{package_dir}.zip'
                    if os.path.isfile(file_extension):
                        print(f"Version {package_version} already exists here {file_extension}")
                        return 0
                else:
                    if os.path.isdir(package_dir):
                        print(f"Version {package_version} already exists here {package_dir}")
                        return 0

                # after we know new file must be created run some scripts to prepare the package internally
                package_scripts = self.file.get("package-scripts", [])
                if not package_scripts or not len(package_scripts):
                    self._debug(f"Nothing to run for {self.name}: package_scripts is empty or missing")
                else:
                    scripts_res, install_duration = self._run_scripts(package_scripts)
                    print(f"package_scripts={self.name!r} has {'succeeded' if scripts_res == 0 else 'FAILED'} "
                          f"duration={install_duration}")

                os.makedirs(package_dir, exist_ok=True)
                if arch_type == 'deb':
                    src_dir = os.path.join(package_dir, self.destination_root)
                else:
                    src_dir = os.path.join(package_dir, "src")

                os.makedirs(src_dir, exist_ok=True)

                copy_locations = self.full_locations + self.just_copy_files
                for fpath in copy_locations:
                    src = fpath
                    dst = None
                    follow_sym_link = True
                    if isinstance(fpath, dict):
                        src = fpath.get("src")
                        dst = fpath.get("dst")
                        follow_sym_link = fpath.get("follow_sym_links", True)
                    src = os.path.abspath(os.path.join(self.abs_location_root, src))
                    src_rel_to_root = os.path.relpath(src, self.abs_location_root)
                    if src_rel_to_root.startswith("../"):
                        raise Exception(f"{src_rel_to_root} is outside location_root={self.location_root}")
                    if not dst:
                        dst = os.path.join(src_dir, src_rel_to_root)
                    else:
                        dst = os.path.join(src_dir, dst)

                    dst_rel_to_root = os.path.relpath(dst, package_dir)
                    if dst_rel_to_root.startswith("../"):
                        raise Exception(f"DST={dst_rel_to_root} is outside package_dir={package_dir}")
                    self._debug(f"copy location:{src} to {dst}")
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    if os.path.isdir(src):
                        shutil.copytree(src, dst, dirs_exist_ok=True, symlinks=follow_sym_link)
                    else:
                        shutil.copy(src, dst, follow_symlinks=follow_sym_link)

                pkg_actions_scripts_dir = os.path.join(package_dir, "actions")
                if arch_type == "deb":
                    pkg_actions_scripts_dir = os.path.join(package_dir, "DEBIAN")
                os.makedirs(pkg_actions_scripts_dir, exist_ok=True)
                for action, fpath in self.package_actions.items():
                    shutil.copy(os.path.join(self.abs_location_root, fpath),
                                os.path.join(pkg_actions_scripts_dir, action))
                    if arch_type == 'deb':
                        os.chmod(os.path.join(pkg_actions_scripts_dir, action), 0o775)
                now_ts = int(datetime.datetime.utcnow().timestamp())
                meta_data = self.file.get("package-info", {})
                meta_data.update({
                    "version": package_version,
                    "name": self.name,
                    "build_ts": now_ts
                })
                write_cfg_file(os.path.join(src_dir, 'info.json'), meta_data, human_readable=True)
                if arch_type:
                    create_package(self, meta_data, arch_type, package_dir, self.args.keep_storage_dir)
                return 0

    def has_changes(self, locations: List) -> bool:
        # let's check if there are changes since this commit
        commit = self.args.check_changes_from_commit
        changes = False
        for loc in locations:
            loc = os.path.join(self.cwd, loc)
            cmd = ["git", "diff", "--name-only", commit, "--", loc]
            resp = subprocess.check_output(cmd, cwd=self.cwd).decode("utf-8").strip()
            if len(resp):
                changes = True
                print(f"In component {self.name} changes are DETECTED! From commit={commit}")
                break
        return changes

    def run(self):
        self.get_root_location()
        self.locations, self.full_locations = self.__get_location_object_list("locations")
        self.git_files = self.__get_location_list('git_only_files')

        _ , self.just_copy_files = self.__get_location_object_list('just_copy')

        self.package_actions = self.file.get("package-actions", {})

        self.all_git_files_to_look = self.locations + self.git_files + list(self.package_actions.values())
        # validate the name
        self.name = self.file.get("name")
        if not self.name:
            raise self.GitComponentException("'name' field is missing")


        print(f"Processing {self.name!r}")

        final_hash = None
        cmp_name_slug = None
        cmp_file_name = None
        info = None
        store_dir = None

        if self.args.check_changes_from_commit and not self.has_changes(self.locations):
            return 0

        if self.args.install_check or self.args.update_check:
            # if there is no update or install then we just stop here
            # validate config files

            # we need to need to check the install or/and update scripts
            store_dir = '/etc/_git_components/'
            if self.args.user:
                store_dir = os.path.join(os.getenv('HOME'), ".git_components")
            if self.args.store_path:
                store_dir = self.args.store_path
            if not os.path.exists(store_dir):
                os.makedirs(store_dir)
            cmp_name_slug = slugify(self.name)
            cmp_file_name = os.path.join(store_dir, f"{cmp_name_slug}.yml")

            final_hash = self.__get_git_version()
            print(final_hash)

            info = self._load_installation_info(cmp_file_name)

            if self.args.install_check and not info:
                # we must run first the install, only then changelog
                print(f"component {self.name} must be installed ...")
                inst_scripts = self.file.get("install-scripts", [])
                if not inst_scripts or len(inst_scripts) == 0:
                    print(f"Nothing to run for {self.name}: install-scripts is empty or missing")
                else:
                    scripts_res, install_duration = self._run_scripts(inst_scripts)
                    print(
                        f"Installation of component={self.name!r} has {'succeeded' if scripts_res == 0 else 'FAILED'}")
                    if scripts_res == 0:
                        info = self._save_installation_info(
                            cmp_file_name,
                            final_hash,
                            self.real_cfg_file,
                            install_duration
                        )
                        self.is_just_installed = True
                    else:
                        return scripts_res

        if self.args.update_check and info and not self.is_just_installed:
            if info['current_version']['hash'] == final_hash:
                print(f"Component {self.name!r} is up to date ...")
            else:
                print(f"Component {self.name!r} must be updated ...")
                update_scripts = self.file.get("update-scripts", [])
                if not update_scripts or len(update_scripts) == 0:
                    print(f"Nothing to run for {self.name}: install-scripts is empty or missing")
                else:
                    scripts_res, scripts_duration = self._run_scripts(update_scripts)
                    print(f"Update of component={self.name!r} has {'succeeded' if scripts_res == 0 else 'FAILED'}")
                    if scripts_res == 0:
                        info = self._save_installation_info(
                            cmp_file_name,
                            final_hash,
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
                print(f"The changelog for {self.name} was already generated ...")
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
                for loc in self.all_git_files_to_look:
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
                        _hash = commit.get("hash")
                        if _hash in unique_commit_hash:
                            continue  # already added
                        unique_commit_hash.append(_hash)
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
        self.process_cmds()


if __name__ == "__main__":
    sys.exit(GitComponent(args_parse()).run())
