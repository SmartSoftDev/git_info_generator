#!/usr/bin/env python3
"""
Copyright (C) Smartsoftdev.eu SRL - All Rights Reserved
For any license violations please contact: SmartSoftDev.eu

This app takes a .git_component.yml config then finds the {COMPONENT_NAME}_changelog.yml and then
generates a simple HTML file.
If you give a configuration files how to generate links to commits, branches, issues then it can link all the artifacts.


NOTE: if you have ideas how to improve this script just create an issue on
https://github.com/SmartSoftDev/git_info_genarator
"""

import os
import datetime
import argparse
import subprocess
import hashlib
import yaml


def args_pars():
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

    args = parser.parse_args()
    cfg.args = args


if __name__ == "__main__":
    main()
