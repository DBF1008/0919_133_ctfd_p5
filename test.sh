#!/usr/bin/env bash
#
# test.sh - run the CTFd unit test suite manually.
#
# Usage:
#   ./test.sh                 # run all unit tests
#   ./test.sh scores          # run only the new scores/standings tests
#   ./test.sh teams users     # run only the given test directories/files
#   ./test.sh -k tiebreak     # pass extra flags/expressions straight to pytest
#
# Requirements (already installed in the project's dev environment):
#   pip install -r requirements.txt
#
# Environment overrides:
#   PYTHON       Python interpreter to use          (default: python3)
#
# Examples:
#   ./test.sh                       # full suite
#   ./test.sh scores                # new scores/standings tests only
#   ./test.sh teams users brackets  # selected test directories
#   ./test.sh -k freeze -x          # extra flags forwarded to pytest
#
set -euo pipefail

cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"

# Pick a pytest entry point that is available with the chosen interpreter.
if "$PYTHON" -c "import pytest" >/dev/null 2>&1; then
    PYTEST=("$PYTHON" -m pytest)
elif command -v pytest >/dev/null 2>&1; then
    PYTEST=(pytest)
else
    echo "pytest is not installed. Install dependencies first:" >&2
    echo "  $PYTHON -m pip install -r requirements.txt" >&2
    exit 1
fi

# Fail early with a clear message if the application dependencies are missing.
"$PYTHON" - <<'PYCHECK'
missing = []
for module in (
    "flask",
    "flask_sqlalchemy",
    "flask_babel",
    "flask_restx",
    "sqlalchemy",
    "sqlalchemy_utils",
    "freezegun",
):
    try:
        __import__(module)
    except ImportError:
        missing.append(module)
if missing:
    raise SystemExit(
        "Missing Python dependencies: "
        + ", ".join(missing)
        + "\nInstall them with: python3 -m pip install -r requirements.txt"
    )
PYCHECK

# Default targets; arguments narrow the selection.
if [[ $# -eq 0 ]]; then
    TARGETS=(tests)
else
    TARGETS=()
    while [[ $# -gt 0 ]]; do
        case "$1" in
            scores)
                TARGETS+=("tests/utils/test_scores.py")
                ;;
            brackets)
                TARGETS+=("tests/brackets")
                ;;
            -*)
                # Any option (e.g. -k, -x, -v) is forwarded verbatim with no
                # default target so pytest applies it to the whole suite.
                TARGETS+=("$@")
                break
                ;;
            *)
                if [[ -e "tests/$1" ]]; then
                    TARGETS+=("tests/$1")
                elif [[ -e "$1" ]]; then
                    TARGETS+=("$1")
                else:
                    echo "Unknown test target: $1" >&2
                    exit 2
                fi
                ;;
        esac
        shift
    done
fi

# Pure flag invocations (e.g. ./test.sh -k foo) apply to the whole suite.
if [[ ${#TARGETS[@]} -eq 0 ]]; then
    TARGETS=(tests)
fi

echo "Running: ${PYTEST[*]} ${TARGETS[*]}"
exec "${PYTEST[@]}" \
    -rf \
    -W ignore::sqlalchemy.exc.SADeprecationWarning \
    -W ignore::sqlalchemy.exc.SAWarning \
    "${TARGETS[@]}"
