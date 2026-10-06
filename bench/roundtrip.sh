#!/usr/bin/env bash
# Round-trip every *.kicad_pcb under the given dirs through kal-roundtrip and check:
#   preserve:  output is byte-identical to the input
#   canonical: the re-laid-out file parses to the same tree
#   drc:       DRC (kal-drc image) on the canonical copy equals DRC on the original
# The canonical copy is written next to the original (<stem>.kal-canonical.kicad_pcb, with
# same-stem project files) so both DRC runs see the same project directory, including
# ${KIPRJMOD}-relative libraries.
# On a DRC mismatch the original is checked a second time: if that run matches the canonical
# copy the board counts as `same`; if the original disagrees with itself the board is
# `nondet` (KiCad is not reproducible on it; reported, not a failure); otherwise `fail`.
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

mapfile -t boards < <(find "$@" -type f -name '*.kicad_pcb' -not -name '*.kal-canonical.kicad_pcb' | sort)
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

# same_drc <a dir> <b dir> [diff file]: true when both drc.json files hold the same violations.
same_drc() {
  python3 orchestrator/drc_compare.py "$1/drc.json" "$2/drc.json" >"${3:-/dev/null}"
}

# longest_line <file>: length of the longest line.
longest_line() {
  awk '{ if (length > m) m = length } END { print m + 0 }' "$1"
}

failures=0
shown=0
for b in "${boards[@]}"; do
  id=$(printf '%s' "${b%.kicad_pcb}" | tr -c 'A-Za-z0-9._-' '_')
  d="$out/$id"
  stem="${b%.kicad_pcb}"
  canon="$stem.kal-canonical"
  mkdir -p "$d"
  : >"$d/errors.log"

  preserve=ok
  "$bin" "$b" "$d/preserved.kicad_pcb" 2>>"$d/errors.log" || preserve=fail

  canonical=ok
  "$bin" "$b" "$canon.kicad_pcb" --canonical 2>>"$d/errors.log" || canonical=fail
  for ext in kicad_pro kicad_dru; do
    if [ -f "$stem.$ext" ]; then cp "$stem.$ext" "$canon.$ext"; fi
  done

  drc_result=skip
  if [ "$canonical" = ok ]; then
    rc_orig=$(drc "$b" "$d/drc-orig")
    if [ "$rc_orig" -ge 2 ]; then
      drc_result=orig-error
    else
      rc_canon=$(drc "$canon.kicad_pcb" "$d/drc-canon")
      if [ "$rc_canon" -ge 2 ]; then
        drc_result=fail
      elif same_drc "$d/drc-orig" "$d/drc-canon" "$d/drc-diff.txt"; then
        drc_result=same
      else
        drc_result=fail
        rc_again=$(drc "$b" "$d/drc-orig2")
        if [ "$rc_again" -lt 2 ]; then
          if same_drc "$d/drc-orig2" "$d/drc-canon"; then
            drc_result=same
          elif ! same_drc "$d/drc-orig" "$d/drc-orig2" "$d/drc-orig-vs-orig.txt"; then
            drc_result=nondet
          fi
        fi
      fi
    fi
  fi

  printf '%s\t%s\t%s\t%s\n' "$b" "$preserve" "$canonical" "$drc_result" >>"$report"
  failed=no
  if [ "$preserve" = fail ] || [ "$canonical" = fail ] || [ "$drc_result" = fail ]; then
    failed=yes
    failures=$((failures + 1))
  fi
  if [ "$failed" = yes ] || [ "$drc_result" = nondet ]; then
    shown=$((shown + 1))
    if [ "$shown" -le 8 ]; then
      echo "--- $b: preserve=$preserve canonical=$canonical drc=$drc_result"
      tail -n 5 "$d/errors.log"
      if [ -f "$d/drc-diff.txt" ]; then
        head -n 12 "$d/drc-diff.txt"
      elif [ "$drc_result" = fail ]; then
        tail -n 5 "$d/drc-canon.log"
        echo "  longest line: original $(longest_line "$b"), canonical $(longest_line "$canon.kicad_pcb")"
      fi
      if [ -f "$d/drc-orig-vs-orig.txt" ]; then
        echo "  original vs original:"
        head -n 6 "$d/drc-orig-vs-orig.txt"
      fi
    fi
  fi
done

echo "boards: ${#boards[@]}, failures: $failures"
awk -F'\t' 'NR > 1 { p[$2]++; c[$3]++; r[$4]++ }
  END {
    for (k in p) printf "  preserve %s: %d\n", k, p[k]
    for (k in c) printf "  canonical %s: %d\n", k, c[k]
    for (k in r) printf "  drc %s: %d\n", k, r[k]
  }' "$report"
if grep -qE $'\t(fail|orig-error|nondet)$' "$report"; then
  echo "problem boards (first 20):"
  grep -E $'\t(fail|orig-error|nondet)' "$report" | head -n 20 || true
fi
if [ "$failures" -ne 0 ]; then
  exit 1
fi
