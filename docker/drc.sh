#!/usr/bin/env bash
# Usage: drc.sh <board.kicad_pcb> [out_dir] [drc_summary args...]
# Writes <out>/kicad_version.txt, <out>/drc.json, <out>/summary.json; prints the text summary.
# Exit: 0 clean, 1 violations (per drc_summary --fail-on), 2 kicad-cli or input failure.
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "usage: drc.sh <board.kicad_pcb> [out_dir] [drc_summary args...]" >&2
  exit 2
fi
board="$1"
out="${2:-out}"
shift $(( $# >= 2 ? 2 : 1 ))

if [ ! -f "$board" ]; then
  echo "drc.sh: board not found: $board" >&2
  exit 2
fi
mkdir -p "$out"

# Determinism: always log the KiCad version next to the report.
kicad-cli version | tee "$out/kicad_version.txt"

set +e
kicad-cli pcb drc --format json --severity-all --refill-zones --exit-code-violations \
  -o "$out/drc.json" "$board" >"$out/kicad-cli.log" 2>&1
rc=$?
set -e
# 0 = clean, 5 = violations found; anything else is a kicad-cli failure.
if [ "$rc" -ne 0 ] && [ "$rc" -ne 5 ]; then
  echo "drc.sh: kicad-cli pcb drc failed (exit $rc)" >&2
  tail -n 30 "$out/kicad-cli.log" >&2
  exit 2
fi

python3 /opt/kal/drc_summary.py "$out/drc.json" --json --fail-on never >"$out/summary.json"
exec python3 /opt/kal/drc_summary.py "$out/drc.json" "$@"
