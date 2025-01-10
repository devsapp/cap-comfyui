#!/bin/bash

source agent/venv/bin/activate
echo "Using python venv, python path '$(which python)', pip path '$(which pip)'... "
python agent/main.py