#!/bin/sh
set -eu
REWARD_FILE=/logs/verifier/reward.txt
mkdir -p /logs/verifier
printf '0\n' > "$REWARD_FILE"
trap 'printf "0\n" > "$REWARD_FILE"; exit 1' HUP INT TERM

ROOT=${TASK_ROOT:-/app}
if [ -x "$ROOT/xrd_stress_report.py" ]; then
  PROGRAM="$ROOT/xrd_stress_report.py"
else
  PROGRAM="$(CDPATH= cd -- "$(dirname -- "$0")/../environment" && pwd)/xrd_stress_report.py"
fi
export PROGRAM
set +e
python3 "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)/verify.py" > /tmp/xrd-verifier-result.json
status=$?
set -e
if [ -s /tmp/xrd-verifier-result.json ]; then
  score=$(python3 -c 'import json,sys; print("%.3f" % float(json.load(open(sys.argv[1]))["score"]))' /tmp/xrd-verifier-result.json 2>/dev/null || printf '0.000')
else
  score='0.000'
fi
printf '%s\n' "$score" > "$REWARD_FILE"
cat /tmp/xrd-verifier-result.json 2>/dev/null || true
exit "$status"
