#!/bin/sh
# Trusted verifier entrypoint.  It deliberately does not inherit the agent's
# Python import paths or execute test Python from the mutable /app worktree.
set -eu

REWARD_FILE=${REWARD_FILE:-/logs/verifier/reward.txt}
TEST_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PYTHON_BIN=${PYTHON_BIN:-/usr/local/bin/python3}
if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN=$(command -v python3)
fi

umask 077
mkdir -p "$(dirname "$REWARD_FILE")"
write_zero() {
  reward_dir=$(dirname "$REWARD_FILE")
  reward_tmp=$(mktemp "$reward_dir/.reward.XXXXXX")
  printf '0.000\n' > "$reward_tmp"
  chmod 600 "$reward_tmp"
  mv -f "$reward_tmp" "$REWARD_FILE"
}
write_zero

WORK_DIR=$(mktemp -d "${TMPDIR:-/tmp}/xrd-verifier.XXXXXX")
TEST_VENV="$WORK_DIR/venv"
RESULT_XML="$WORK_DIR/results.xml"
cleanup() {
  rm -rf "$WORK_DIR"
}
interrupt() {
  write_zero
  cleanup
  exit 1
}
trap cleanup EXIT
trap interrupt HUP INT TERM

# Regression guard: a sitecustomize.py in an agent-controlled current directory
# must neither run at interpreter startup nor overwrite the protected reward.
PROBE_DIR="$WORK_DIR/startup-probe"
mkdir -p "$PROBE_DIR"
PROBE_MARKER="$PROBE_DIR/imported"
cat > "$PROBE_DIR/sitecustomize.py" <<'PY'
import atexit
import os
from pathlib import Path

Path(os.environ["PROBE_MARKER"]).write_text("imported", encoding="utf-8")
atexit.register(lambda: Path(os.environ["REWARD_FILE"]).write_text("1.000\n", encoding="utf-8"))
PY
(
  cd "$PROBE_DIR"
  env -i \
    PATH="/usr/local/bin:/usr/bin:/bin" \
    HOME="$WORK_DIR/home" \
    LANG="C.UTF-8" \
    LC_ALL="C.UTF-8" \
    PROBE_MARKER="$PROBE_MARKER" \
    REWARD_FILE="$REWARD_FILE" \
    "$PYTHON_BIN" -I -c 'import sys; assert sys.flags.isolated == 1'
)
if [ -e "$PROBE_MARKER" ] || [ "$(cat "$REWARD_FILE")" != '0.000' ]; then
  echo 'verifier startup isolation check failed' >&2
  exit 1
fi

# Test dependencies are installed only into a verifier-private virtualenv.
"$PYTHON_BIN" -m venv "$TEST_VENV"
"$TEST_VENV/bin/python" -m pip install \
  --disable-pip-version-check \
  --no-cache-dir \
  --no-index \
  --find-links="$TEST_DIR/wheels" \
  --require-hashes \
  -r "$TEST_DIR/requirements-test.txt"

# Run from the read-only test mount with an empty, allowlisted environment.
# -I ignores the candidate's PYTHONPATH, user site, sitecustomize.py and .pth
# files reachable through the mutable application directory.
set +e
(
  cd "$TEST_DIR"
  env -i \
    PATH="/usr/local/bin:/usr/bin:/bin" \
    HOME="$WORK_DIR/home" \
    LANG="C.UTF-8" \
    LC_ALL="C.UTF-8" \
    REWARD_FILE="$REWARD_FILE" \
    "$TEST_VENV/bin/python" -I -m pytest -q -p no:cacheprovider \
      --junitxml="$RESULT_XML" \
      "$TEST_DIR/test_outputs.py"
)
status=$?
set -e

# Scoring is a separate, isolated post-processing step.  It replaces the
# initialized zero atomically only when the test report is structurally sound.
if ! env -i \
  PATH="/usr/local/bin:/usr/bin:/bin" \
  HOME="$WORK_DIR/home" \
  LANG="C.UTF-8" \
  LC_ALL="C.UTF-8" \
  REWARD_FILE="$REWARD_FILE" \
  RESULT_XML="$RESULT_XML" \
  PYTEST_STATUS="$status" \
  "$PYTHON_BIN" -I "$TEST_DIR/score_reward.py"; then
  write_zero
fi

if [ ! -s "$REWARD_FILE" ]; then
  write_zero
fi
exit "$status"
