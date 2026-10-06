#!/usr/bin/env bash
# Usage: drc.sh <board.kicad_pcb> [out_dir] [drc_summary args...]
# Writes <out>/kicad_version.txt, <out>/drc.json, <out>/summary.json; prints the text summary.
# Exit: 0 clean, 1 violations (per drc_summary --fail-on), 2 kicad-cli or input failure,
# 3 timeout (KAL_DRC_TIMEOUT).
# Env: KAL_DRC_REFILL=0 skips --refill-zones; KAL_DRC_TIMEOUT=<seconds> limits kicad-cli.
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

drc_args=(--format json --severity-all --exit-code-violations)
# --refill-zones exists from KiCad 10; 9.x rejects it as an unknown argument.
# KAL_DRC_REFILL=0 checks zones as saved: for comparing two files (round-trip) a refill only
# adds run time and nondeterminism. Final DRC keeps the default (refill, rule 2).
if [ "${KAL_DRC_REFILL:-1}" = 0 ]; then
  echo "drc.sh: KAL_DRC_REFILL=0; zones are checked as saved" >&2
else
  drc_help=$(kicad-cli pcb drc --help 2>&1 || true)
  if grep -q -- '--refill-zones' <<<"$drc_help"; then
    drc_args+=(--refill-zones)
  else
    echo "drc.sh: kicad-cli has no --refill-zones; zones are checked as saved" >&2
  fi
fi

# KAL_DRC_TIMEOUT=<seconds> stops kicad-cli after that long (exit 3).
limit=()
if [ -n "${KAL_DRC_TIMEOUT:-}" ]; then
  limit=(timeout "$KAL_DRC_TIMEOUT")
fi

set +e
"${limit[@]}" kicad-cli pcb drc "${drc_args[@]}" -o "$out/drc.json" "$board" >"$out/kicad-cli.log" 2>&1
rc=$?
set -e
if [ "${#limit[@]}" -gt 0 ] && [ "$rc" -eq 124 ]; then
  echo "drc.sh: kicad-cli pcb drc timed out after ${KAL_DRC_TIMEOUT}s" >&2
  exit 3
fi
# 0 = clean, 5 = violations found; anything else is a kicad-cli failure.
if [ "$rc" -ne 0 ] && [ "$rc" -ne 5 ]; then
  echo "drc.sh: kicad-cli pcb drc failed (exit $rc)" >&2
  tail -n 30 "$out/kicad-cli.log" >&2
  exit 2
fi

python3 /opt/kal/drc_summary.py "$out/drc.json" --json --fail-on never >"$out/summary.json"
exec python3 /opt/kal/drc_summary.py "$out/drc.json" "$@"
