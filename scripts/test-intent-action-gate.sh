#!/usr/bin/env sh
set -eu

python3 -m unittest discover -s hermes-plugins/tests -p 'test_*.py' -v
