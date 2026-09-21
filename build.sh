#!/usr/bin/env bash
set -o errexit
pip install -r requirements.txt

# Fail the build early if any application Python file has a syntax error.
python -m compileall -q app
