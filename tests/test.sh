#!/bin/sh
set -eu
REWARD_FILE=${REWARD_FILE:-/logs/verifier/reward.txt}
mkdir -p "$(dirname "$REWARD_FILE")"
printf '0\n' > "$REWARD_FILE"
trap 'printf "0\n" > "$REWARD_FILE"; exit 1' HUP INT TERM

TEST_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
export REWARD_FILE
set +e
python3 -m pytest -q "$TEST_DIR/test_outputs.py"
status=$?
set -e
case "$status" in
  0|1) ;;
  *) printf '0\n' > "$REWARD_FILE" ;;
esac
if [ ! -s "$REWARD_FILE" ]; then
  printf '0\n' > "$REWARD_FILE"
fi
exit "$status"
