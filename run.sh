#!/bin/bash

if [ ! -d .venv ] ; then
  virtualenv --python=$(which python2) .venv
fi

source .venv/bin/activate
if [ ! -d .venv ] ; then
  pip install pyyaml Jinja2 pathlib ruamel.yaml
fi

rm -rf output
python lavasetup-gen.py -v 3 $@

# cleanup virtualenv
deactivate
#rm -rf .venv
