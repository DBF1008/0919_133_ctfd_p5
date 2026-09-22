#!/usr/bin/env bash
# Run the CTFd unit test suite.
#
# Usage:
#   ./test.sh                      # run all unit tests
#   ./test.sh tests/utils/test_scores.py   # run specific test script(s)
#   ./test.sh -k tie_break         # pass extra pytest args
set -euo pipefail
cd "$(dirname "$0")"

# Default to the whole suite when no arguments are given
if [ "$#" -eq 0 ]; then
  set -- tests/
fi

exec pytest -rf \
  --ignore-glob="**/node_modules/" \
  --ignore=node_modules/ \
  -W ignore::sqlalchemy.exc.SADeprecationWarning \
  -W ignore::sqlalchemy.exc.SAWarning \
  "$@"
