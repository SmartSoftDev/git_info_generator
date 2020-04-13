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
import re
import yaml
from jinja2 import Environment, PackageLoader, select_autoescape


def slugify(text):
    return re.sub(r'[\W_]+', '-', text)


class ChangelogSimpleHtml:
    class ChangeLogException(Exception):
        pass

    DEF_CMP_FILE_NAME = '.git_component.yml'
    DEF_GLOBAL_STORE_DIR = '/etc/_git_components/'
    DEF_USER_STORE_DIR = '.git_components/'
    CHANGELOG_FILE_NAME = '{cmp_name_slug}_changelog.yml'

    def __init__(self, args):
        self.args = args
        self.out = args.out
        if not os.path.exists(self.out):
            os.makedirs(os.path.dirname(self.out))

        if os.path.isdir(self.out):
            self.out = os.path.join(self.out, 'index.html')

        self.j_env = Environment(
            loader=PackageLoader('tpls', '.'),
            autoescape=select_autoescape(['html', 'xml'])
        )
        if args.config:
            self.file = os.path.realpath(args.config)
            if os.path.isdir(self.file):
                self.file = os.path.join(self.file, self.DEF_CMP_FILE_NAME)
        else:
            self.file = self.DEF_CMP_FILE_NAME
        if not os.path.exists(self.file):
            raise self.ChangeLogException(f"git_component config file not found in {self.file}")
        with open(self.file, "r") as f:
            self.info = yaml.safe_load(f)
        self.name = self.info.get("name")
        if self.name is None:
            raise self.ChangeLogException(f"git_component config does not have name filed in {self.file}")
        self.name_slug = slugify(self.name)
        changelog_file_name = self.CHANGELOG_FILE_NAME.format(cmp_name_slug=self.name_slug)
        if self.args.user:
            self.changelog_file = os.path.join(
                os.getenv("HOME"),
                self.DEF_USER_STORE_DIR,
                changelog_file_name)
        else:
            self.changelog_file = os.path.join(
                self.DEF_GLOBAL_STORE_DIR,
                changelog_file_name)
        if self.args.store_path:
            self.changelog_file = os.path.join(self.args.store_path, changelog_file_name)
        if not os.path.exists(self.changelog_file):
            raise self.ChangeLogException(f"Changelog file is not found: {self.changelog_file}")

        with open(self.changelog_file, "r") as f:
            self.changelog = yaml.safe_load(f)

    def run(self):
        template = self.j_env.get_template('index.jinja2')
        variables = {
            "name": self.name,
            "history": self.changelog.get("history", [])
        }
        with open(self.out, "w+") as f:
            f.write(template.render(**variables))


def args_pars():
    parser = argparse.ArgumentParser(
        description='Compute a hash of multiple git locations')
    parser.add_argument('-v', '--debug', action='count',
                        default=0, help='Enable debugging')
    parser.add_argument('-c', '--config', action='store', type=str, default=None,
                        help=f'Path to the git_component config file, or directory where '
                             f'{ChangelogSimpleHtml.DEF_CMP_FILE_NAME} is located (default=.)')
    parser.add_argument('-l', '--link-config', action='store', type=str, default=None,
                        help='Path to link generation config file (yml)')
    parser.add_argument('out', action='store', type=str, default=None,
                        help='path to the file or directory to write the results to')
    parser.add_argument('--user', action='store_true', default=None,
                        help='sets path to the git_component store to $HOME/.git_components/')
    parser.add_argument('-s', '--store-path', action='store', type=str, default=None,
                        help='path to the git_component store (where changelog file is located)'
                        '(default=/etc/_git_components/')
    return parser.parse_args()


def main():
    args = args_pars()
    app = ChangelogSimpleHtml(args)
    app.run()


if __name__ == "__main__":
    main()
