#!/bin/bash
DIR=$(readlink -e $(dirname ${BASH_SOURCE[0]})/../)

sudo ln -sf $DIR/src/bin/git_component.py /bin/git_component
