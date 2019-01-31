#!/bin/bash

if [ ! -d .venv ] ; then
  virtualenv --python=$(which python2) .venv
  source .venv/bin/activate
  pip install -r requirements.txt
else
  source .venv/bin/activate
fi


rm -rf output
python lavasetup-gen.py -v 3 $@

# cleanup virtualenv
deactivate
#rm -rf .venv
