import json
import os
import re
import subprocess
import uuid
from typing import Union, List

# equivalent to [^a-zA-Z0-9]
NON_ALPHANUM_PATTERN = re.compile(r'[\W_]+')


def slugify(text):
    return NON_ALPHANUM_PATTERN.sub('-', text)


def gen_random_hash():
    return uuid.uuid4().hex


def get_last_tag(cwd, _filter: str) -> Union[None, str]:
    """get last tag for some specific component"""
    cmd = ["git", "tag", "--list", _filter, "--merged"]
    tags = []
    try:
        tags = [
            line.strip()
            for line in subprocess.check_output(cmd, cwd=cwd, stderr=subprocess.STDOUT)
            .decode("utf-8")
            .strip()
            .split("\n")
            if line.strip()
        ]
    except subprocess.CalledProcessError:
        print(f"Found no tags for {_filter} pattern.")
    if tags:
        return tags[-1]
    return


def compose_build_commit_hash(cwd, tag, files: List, hash_limit=7) -> str:
    commits_hashes = []
    cmd = ["git", "log", "--format=%H", "--", *files]
    if tag:
        # get all commits hashes from last tag until head
        cmd = ["git", "log", "--format=%H", f"{tag}..HEAD", "--", *files]
    try:
        commits_hashes = subprocess.check_output(cmd, cwd=cwd, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError:
        pass
    if commits_hashes:
        commits_hashes = [c.strip() for c in commits_hashes.decode().strip().split("\n") if c.strip()]
    changes_count = len(commits_hashes)
    # the build_commit_hash: -20-65ecc13
    build_commit_hash = ""
    if changes_count > 0:
        # creates build_commit_hash with git short hash ex: "20-65ecc13"
        build_commit_hash = f"-{changes_count}"
        build_commit_hash += f"-{commits_hashes[0][:hash_limit]}"
    return build_commit_hash


def write_cfg_file(file_path, data, human_readable=False):
    """writes json file.
    NOTE: it will always write in an atomic manner (first write to tmp file then move it to destination
    when writing configuration files is IMPORTANT to protect against powerOFF events and do not leave the CFG file
    half written.
    """

    tmp_file_path = file_path + ".tmp"
    with open(tmp_file_path, "w+") as f:
        json.dump(data, f, indent=2 if human_readable else None)
        f.flush()
        os.fsync(f.fileno())
    # rename should be atomic operation
    os.rename(tmp_file_path, file_path)
    # still we would like to sync the hole parent directory.
    dir_name = os.path.dirname(file_path)
    if not dir_name:
        dir_name = '.'
    dir_fd = os.open(dir_name, os.O_DIRECTORY | os.O_CLOEXEC)
    os.fsync(dir_fd)
    os.close(dir_fd)
