#!/bin/bash
DIR=$(readlink -e $(dirname ${BASH_SOURCE[0]})/../)

sudo ln -sf $DIR/src/git_component.py /bin/git_component
sudo ln -sf $DIR/src/gen_changelog_simple_html.py /bin/gen_changelog_simple_html
