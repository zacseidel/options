#!/bin/bash
#
# Daily update, driven by ~/Library/LaunchAgents/com.zacseidel.market.daily.plist
# (source of truth: ops/launchd/com.zacseidel.market.daily.plist).
#
# Fires weekdays at 17:30 local, with catch-ups at 20:30 and 07:00. This script decides whether
# a firing should do the work:
#   * on battery  -> skip; a later firing picks it up once plugged in
#   * already ran -> skip; a stamp records the last session date completed successfully
# Logs: ~/Library/Logs/market/ (90 days kept).
#   ops/launchd/run.sh           same guards as the scheduled run
#   ops/launchd/run.sh --force   ignore battery and already-ran guards
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOG_DIR="$HOME/Library/Logs/market"
STAMP="$LOG_DIR/last-success-day"
PYTHON="$REPO/.venv/bin/python"
export PATH="/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

FORCE=0
[[ "${1:-}" == "--force" ]] && FORCE=1
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/run-$(date +%Y-%m-%d-%H%M%S).log"
exec > >(tee -a "$LOG") 2>&1
say() { echo "$(date '+%Y-%m-%d %H:%M:%S')  $*"; }

# The 07:00 catch-up belongs to the previous day's session.
if [[ 10#$(date +%H) -lt 12 ]]; then day="$(date -v-1d +%Y-%m-%d)"; else day="$(date +%Y-%m-%d)"; fi

if [[ $FORCE -eq 0 ]]; then
  if ! pmset -g ps | grep -q "AC Power"; then say "SKIP: on battery"; exit 0; fi
  if [[ -f "$STAMP" && "$(cat "$STAMP")" == "$day" ]]; then say "SKIP: already ran for $day"; exit 0; fi
fi

say "=== market daily update for $day ==="
cd "$REPO" || exit 1
"$PYTHON" -m market.ops.run
status=$?
if [[ $status -eq 0 ]]; then echo "$day" > "$STAMP"; say "DONE"; else say "FAILED ($status); a later firing will retry"; fi
find "$LOG_DIR" -name 'run-*.log' -mtime +90 -delete 2>/dev/null
exit $status
