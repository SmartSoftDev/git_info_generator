#!/usr/bin/env python3
"""
Copyright (C) Smartsoftdev.eu SRL - All Rights Reserved
For any license violations please contact: SmartSoftDev.eu
"""
import argparse
import json
import datetime
import hashlib
import logging
import os
import shutil
import subprocess
import sys
from timeit import default_timer as timer
from typing import List

import yaml

from utils import (
    slugify,
    write_cfg_file,
    compose_build_commit_hash,
    get_last_tag,
    gen_random_hash,
    compute_string_json_check_sum,
    utc_now_iso,
    parse_commits,
)


class AbortException(Exception):
    pass


def args_parse():
    parser = argparse.ArgumentParser(description="Compute a hash of multiple git locations")
    parser.add_argument("-v", "--verbose", action="count", default=0, help="Enable debugging")
    parser.add_argument(
        "-c",
        "--config",
        type=str,
        default=None,
        help="Path to the yaml config file, or directory where .git_component.yml (default=.)",
    )
    parser.add_argument(
        "-F",
        "--change_log_from",
        type=str,
        nargs="+",
        default=None,
        help="If history is missing, used as git reference. format: LOCATION:REF",
    )
    return parser.parse_args()


class GitComponent:
    DEF_CMP_FILE_NAME = ".git_component.yml"
    DEF_GLOBAL_STORE_DIR = "/etc/_git_components/"
    DEF_USER_STORE_DIR = ".git_components/"
    CHANGELOG_FILE_NAME = "{cmp_name_slug}_changelog.yml"
    CHANGELOG_FILE_FORMAT_VERSION = "v1.0.0"

    def __init__(self, args):
        self.args = args
        if self.args.verbose > 2:
            self.args.verbose = 2
        print(f"{self.args=}")
        log_mappings = {1: logging.INFO, 2: logging.DEBUG}
        log_format = "%(asctime)s.%(msecs).3d|%(levelname)7s|| %(message)s || %(filename)s:%(lineno).d"
        logging.basicConfig(level=log_mappings.get(self.args.verbose, logging.INFO), format=log_format)
        self.log = logging.getLogger(__name__)
        cfg_file = self.DEF_CMP_FILE_NAME
        if self.args.config:
            if os.path.isdir(self.args.config):
                cfg_file = os.path.join(self.args.config, self.DEF_CMP_FILE_NAME)
            else:
                cfg_file = self.args.config
        if not os.path.exists(cfg_file):
            raise AbortException(f"Config file {cfg_file} NOT found!")
        self.cwd = os.path.abspath(os.path.dirname(cfg_file))
        self.real_cfg_file = os.path.abspath(cfg_file)
        with open(cfg_file, "r") as f:
            self.file = yaml.safe_load(f)

    def _debug(self, txt):
        if self.args.verbose:
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

    def __get_location_object_list(self, field):
        pre_component_field = self.file.get(field, [])
        if pre_component_field is None:
            raise AbortException(f"Config file has no '{field}' list!")
        if not isinstance(pre_component_field, list):
            raise pre_component_field(f"'{field}' field from config file MUST be a list!")
        component_field = []
        for el in pre_component_field:
            if isinstance(el, dict):
                new_src = el.get("to_root")
                if new_src:
                    el = {"src": new_src, "dst": os.path.basename(new_src)}
            component_field.append(el)

        for el in component_field:
            if isinstance(el, dict):
                if not (el.get("src") and el.get("dst")) and not (len(el.get("src")) and len(el.get("dst"))):
                    raise AbortException(
                        f"'{field}' must contain list of str or dict with non empty 'src' and 'dst' keys"
                    )
            elif isinstance(el, (int, float, str)):
                if not len(el):
                    raise AbortException(f"'{field}' contains empty strings")
            else:
                raise AbortException(
                    f"'{field}' must contain list of str or dict with non empty " f"'src' and 'dst' keys"
                )
        path_list = [el.get("src") if isinstance(el, dict) else el for el in component_field]
        return path_list, component_field

    def __get_location_list(self, field):
        component_field = self.file.get(field, [])
        ret = []
        for el in component_field:
            if not isinstance(el, (int, float, str)):
                raise AbortException(f"'{field}' must be string")
            el = str(el)
            if not el:
                raise AbortException(f"'{field}' contains empty strings")
            ret.append(el)

        return ret

    def run(self):
        self.locations, self.full_locations = self.__get_location_object_list("locations")
        self.git_files = self.__get_location_list("git_only_files")

        _, self.just_copy_files = self.__get_location_object_list("just_copy")

        self.package_actions = self.file.get("package-actions", {})
        self.all_git_files_to_look = self.locations + self.git_files + list(self.package_actions.values())
        # validate the name
        self.name = self.file.get("name")
        if not self.name:
            raise AbortException("'name' field is missing")
        self.name_slug = slugify(self.name)
        self.get_root_location()

        self._cmd_gen_changelog()
        return 0

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
                raise AbortException(f"Could not get git remote repo from {loc}, is it under git control?")
            repo = resp
            if repo not in repos:
                cmd = ["git", "log", "-n1", "--format=%H", "--", loc]
                resp = subprocess.check_output(cmd, cwd=repo_cwd).decode("utf-8").strip()
                if len(resp) == 0:
                    raise AbortException(f"Could not get git commit for the repo from {loc}, is it under git control?")
                repo_hash = resp
                repos[repo] = repo_hash
        return repos

    def _cmd_gen_changelog(self):
        # Changelog must be executed before updating to the newest version
        cmp_changelog_file_path = os.path.join(self.cwd, f"{self.name_slug}_changelog.yml")
        if os.path.exists(cmp_changelog_file_path):
            with open(cmp_changelog_file_path, "r") as f:
                current_changelog_info = yaml.safe_load(f)
        else:
            current_changelog_info = {"history": [], "name": self.name}
        cl_info = {
            "repos": {},
            "final_hash": "",
            "generated_at": utc_now_iso(),
            "changelog_format": self.CHANGELOG_FILE_FORMAT_VERSION,
        }
        repos = self._get_repo_hash(self.all_git_files_to_look)
        cl_info["repos"] = repos
        final_hash = cl_info["final_hash"] = (
            list(repos.values())[0] if len(repos) == 1 else compute_string_json_check_sum(repos)
        )
        previous_run = None
        if len(current_changelog_info["history"]) > 0:
            if current_changelog_info["history"][0]["final_hash"] == final_hash:
                print(f"The changelog for {self.name} was already generated ...")
                return
            previous_run = current_changelog_info["history"][0]
        self.log.debug("cl_info=%r", cl_info)
        print(f"Generate changelog ... ")

        changelog = {}
        unique_commit_hash = []
        previous_repos = {}
        provided_log_from = {}
        used_references = {}
        if self.args.change_log_from:
            for i in self.args.change_log_from:
                items = i.split(":", 1)
                provided_log_from[items[0]] = items[1]
        if previous_run:
            previous_repos = previous_run.get("repos")

        for loc in self.all_git_files_to_look:
            org_loc = loc
            loc = os.path.join(self.abs_location_root, loc)
            if os.path.isfile(loc):
                repo_cwd = os.path.dirname(loc)
            else:
                repo_cwd = loc
            cmd = ["git", "ls-remote", "--get-url"]
            resp = subprocess.check_output(cmd, cwd=repo_cwd).decode("utf-8").strip()
            if len(resp) == 0:
                raise AbortException(f"Could not get git remote repo from {loc}," f" is it under git control?")
            repo = resp
            loc = os.path.join(self.abs_location_root, loc)
            cmd = ["git", "log", "--format=_#._%H|$.|%aN|$.|%aI|$.|%s|$.|%ae|$.|%b"]
            used_ref = None
            if repo in previous_repos:
                used_ref = previous_repos[repo]
            else:
                ref = provided_log_from.get(org_loc)
                self.log.debug("Could not find repo=%r loc=%r in previous changelogs", repo, org_loc)
                if ref:
                    self.log.debug("using provided reference=%r for loc=%r", ref, org_loc)
                    used_ref = ref
            if used_ref:
                cmd.append(f"{used_ref}..HEAD")
                used_references[repo] = used_ref
            if org_loc != ".":
                cmd += ["--", org_loc]
            self.log.debug("run %r", " ".join(cmd))
            resp = subprocess.check_output(cmd, cwd=repo_cwd).decode("utf-8").strip()
            commits = parse_commits(resp)
            print(f"Got {len(commits)} commits")
            for commit in commits:
                _hash = commit.get("hash")
                if _hash in unique_commit_hash:
                    continue  # already added
                unique_commit_hash.append(_hash)
                if repo not in changelog:
                    changelog[repo] = []
                changelog[repo].append(commit)
        # self.log.debug("cl %r", changelog)
        cl_info["changelog"] = changelog
        if used_references:
            cl_info["used_references"] = used_references

        current_changelog_info["history"].insert(0, cl_info)
        with open(cmp_changelog_file_path, "w+") as f:
            yaml.safe_dump(current_changelog_info, f)


if __name__ == "__main__":
    try:
        sys.exit(GitComponent(args_parse()).run())
    except AbortException as e:
        print(f"FATAL: {e}")
        sys.exit(88)
