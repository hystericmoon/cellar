#!/bin/bash
# Runs both test suites against the simulated phone (Linux test container only).
#   tests/run_all.sh            → API suite (35 checks) + browser suite (28 checks)
# Each suite starts from a clean phone; the server is restarted so old transfer history can't confuse checks.
set -u
T="$(cd "$(dirname "$0")" && pwd)"; ROOT="$(dirname "$T")"
export HOME_FAKE=1
python3 "$T/setup_fake_phone.py" >/dev/null
echo '{"devs": [["FAKE123", "usb"]], "mdns": []}' > "$T/fakebin/state.json"

restart() {
  pkill -f '^python3 cellar.py' 2>/dev/null; sleep 0.5
  (cd "$ROOT" && ADB="$T/fakebin/adb" CELLAR_NO_BROWSER=1 nohup python3 cellar.py < /dev/null > "$T/server.log" 2>&1 &)
  for _ in $(seq 1 20); do curl -s -o /dev/null http://127.0.0.1:8765/ && return; sleep 0.3; done
  echo "server didn't start; see tests/server.log"; exit 1
}
clean() {
  python3 "$T/reset.py" >/dev/null
  python3 -c "
import os, shutil
p = '/storage/emulated/0/DCIM/Camera/NEW_1.jpg'
os.path.exists(p) and os.remove(p)
shutil.rmtree('/storage/emulated/0/Download/Work', ignore_errors=True)"
}

restart; clean
echo "== API suite"; (cd "$T" && python3 api_test.py) | tee "$T/api.out" | grep -v '^PASS'
API_PASS=$(grep -c '^PASS' "$T/api.out"); API_FAIL=$(grep -c '^FAIL' "$T/api.out")

restart; clean
echo "== Browser suite"; (cd "$T" && node e2e.js "$T/fixtures/SocSaver") | tee "$T/e2e.out" | grep -v '^PASS'
E2E_PASS=$(grep -c '^PASS' "$T/e2e.out"); E2E_FAIL=$(grep -c '^FAIL' "$T/e2e.out")

pkill -f '^python3 cellar.py' 2>/dev/null
echo; echo "API: $API_PASS passed, $API_FAIL failed · Browser: $E2E_PASS passed, $E2E_FAIL failed"
[ "$API_FAIL" -eq 0 ] && [ "$E2E_FAIL" -eq 0 ]
