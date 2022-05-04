#!/bin/bash
DIR=$(readlink -f $(dirname ${BASH_SOURCE[0]})/../)

sudo ln -sf $DIR/src/git_component.py /bin/git_component
sudo ln -sf $DIR/src/gen_changelog_simple_html.py /bin/gen_changelog_simple_html

sudo -H pip3 install -r $DIR/scripts/requirements.txt --upgrade