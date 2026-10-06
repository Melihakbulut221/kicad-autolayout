#!/usr/bin/env bash
# Round-trip every *.kicad_pcb under the given dirs through kal-roundtrip and check:
#   preserve:  output is byte-identical to the input
#   canonical: the re-laid-out file parses to the same tree
#   drc:       DRC (kal-drc image) on the canonical copy equals DRC on the original
# Usage: bench/roundtrip.sh <kal-roundtrip> <kal-drc image> <out dir> <dir>...
# Board and out paths must be relative to $PWD (mounted at /work in the DRC container).
# Writes <out>/report.tsv; exit 0 all pass, 1 any failure, 2 usage error or no boards.
set -euo pipefail

if [ $# -lt 4 ]; then
  echo "usage: roundtrip.sh <kal-roundtrip> <kal-drc image> <out dir> <dir>..." >&2
  exit 2
fi
bin=$(realpath "$1")
image="$2"
out="$3"
shift 3

mapfile -t boards < <(find "$@" -type f -name '*.kicad_pcb' | sort)
if [ ${#boards[@]} -eq 0 ]; then
  echo "roundtrip.sh: no .kicad_pcb files under $*" >&2
  exit 2
fi
mkdir -p "$out"
report="$out/report.tsv"
printf 'board\tpreserve\tcanonical\tdrc\n' >"$report"

# drc <board> <out dir>: prints drc.sh's exit code (0 clean, 1 violations, 2 failure).
drc() {
  local rc=0
  docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp -v "$PWD:/work" "$image" \
    "$1" "$2" >"$2.log" 2>&1 || rc=$?
  echo "$rc"
}

failures=0
for b in "${boards[@]}"; do
  id=$(printf '%s' "${b%.kicad_pcb}" | tr -c 'A-Za-z0-9._-' '_')
  d="$out/$id"
  base=$(basename "$b")
  stem="${b%.kicad_pcb}"
  mkdir -p "$d/canon"

  preserve=ok
  "$bin" "$b" "$d/preserved.kicad_pcb" 2>>"$d/errors.log" || preserve=fail

  canonical=ok
  "$bin" "$b" "$d/canon/$base" --canonical 2>>"$d/errors.log" || canonical=fail
  # Same project settings next to the canonical copy, so DRC uses the same rules.
  for ext in kicad_pro kicad_dru; do
    if [ -f "$stem.$ext" ]; then cp "$stem.$ext" "$d/canon/${base%.kicad_pcb}.$ext"; fi
  done
  if [ -f "$(dirname "$b")/fp-lib-table" ]; then cp "$(dirname "$b")/fp-lib-table" "$d/canon/"; fi

  drc_result=skip
  if [ "$canonical" = ok ]; then
    rc_orig=$(drc "$b" "$d/drc-orig")
    if [ "$rc_orig" -ge 2 ]; then
      drc_result=orig-error
    else
      rc_canon=$(drc "$d/canon/$base" "$d/drc-canon")
      if [ "$rc_canon" -ge 2 ]; then
        drc_result=fail
      elif python3 orchestrator/drc_compare.py "$d/drc-orig/drc.json" "$d/drc-canon/drc.json" \
        >"$d/drc-diff.txt"; then
        drc_result=same
      else
        drc_result=fail
      fi
    fi
  fi

  printf '%s\t%s\t%s\t%s\n' "$b" "$preserve" "$canonical" "$drc_result" >>"$report"
  if [ "$preserve" = fail ] || [ "$canonical" = fail ] || [ "$drc_result" = fail ]; then
    failures=$((failures + 1))
  fi
done

echo "boards: ${#boards[@]}, failures: $failures"
awk -F'\t' 'NR > 1 { p[$2]++; c[$3]++; r[$4]++ }
  END {
    for (k in p) printf "  preserve %s: %d\n", k, p[k]
    for (k in c) printf "  canonical %s: %d\n", k, c[k]
    for (k in r) printf "  drc %s: %d\n", k, r[k]
  }' "$report"
if [ "$failures" -ne 0 ] || grep -q $'\torig-error$' "$report"; then
  echo "problem boards (first 10):"
  grep -E $'\t(fail|orig-error)' "$report" | head -n 10 || true
fi
if [ "$failures" -ne 0 ]; then
  exit 1
fi
