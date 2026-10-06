#!/usr/bin/env python3
"""Score extracted constraints against a human-labeled set (phase 1 target: precision >= 90%).

Both files are constraint documents (docs/constraints.md); both are validated and normalized
first, so mm values compare as integer nm. A predicted constraint matches a labeled one when
the type and every type-specific field are equal; `id`, `approved`, `approved_by` and `note`
are ignored, and net lists that are sets (selectors, length_match nets, netclass patterns)
compare without order. Each labeled constraint is matched at most once. A match whose
`source.page` differs is counted as a source error (rule 6 needs the right page).

Usage:
    python3 orchestrator/extract_eval.py predicted.json labeled.json [--json] [--min-precision 0.9]
Exit: 0 ok (and precision >= --min-precision if given), 1 below threshold or invalid
document, 2 unreadable input.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import constraints as cs

IGNORED = {"id", "approved", "approved_by", "note", "source"}
UNORDERED = {"nets", "patterns"}


def _canon(value: object, key: str = "") -> object:
    if isinstance(value, dict):
        return tuple(sorted((k, _canon(v, k)) for k, v in value.items()))
    if isinstance(value, list):
        items = [_canon(v) for v in value]
        return tuple(sorted(items)) if key in UNORDERED else tuple(items)
    return value


def match_key(c: dict) -> tuple:
    """What has to agree for a predicted constraint to count as the labeled one."""
    return _canon({k: v for k, v in c.items() if k not in IGNORED})


def score(predicted: list[dict], labeled: list[dict]) -> dict:
    pool: dict[tuple, list[dict]] = {}
    for c in labeled:
        pool.setdefault(match_key(c), []).append(c)
    tp = Counter()
    source_errors, false_pos = [], []
    for c in predicted:
        candidates = pool.get(match_key(c))
        if not candidates:
            false_pos.append(c["id"])
            continue
        # Prefer a labeled constraint with the same page, so source errors are not inflated.
        same = [x for x in candidates if str(x["source"]["page"]) == str(c["source"]["page"])]
        hit = (same or candidates)[0]
        candidates.remove(hit)
        tp[c["type"]] += 1
        if not same:
            source_errors.append(c["id"])
    missed = [c["id"] for cands in pool.values() for c in cands]
    n_tp = sum(tp.values())
    by_type = {}
    for t in sorted({c["type"] for c in predicted + labeled}):
        p = sum(c["type"] == t for c in predicted)
        lab = sum(c["type"] == t for c in labeled)
        by_type[t] = {"predicted": p, "labeled": lab, "matched": tp[t]}
    return {
        "predicted": len(predicted),
        "labeled": len(labeled),
        "matched": n_tp,
        "precision": n_tp / len(predicted) if predicted else None,
        "recall": n_tp / len(labeled) if labeled else None,
        "source_errors": source_errors,
        "false_positives": false_pos,
        "missed": missed,
        "by_type": by_type,
    }


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{100 * x:.1f}%"


def _load(path: Path) -> tuple[list[dict] | None, list[str]]:
    doc = cs.load_file(path)
    constraints, errors = cs.validate(doc)
    return (None if errors else constraints), [f"{path}: {e}" for e in errors]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("predicted", type=Path)
    p.add_argument("labeled", type=Path)
    p.add_argument("--json", action="store_true", help="print the full score as JSON")
    p.add_argument("--min-precision", type=float, default=None)
    args = p.parse_args(argv)

    try:
        predicted, errors = _load(args.predicted)
        labeled, more = _load(args.labeled)
    except cs.FileError as e:
        print(f"extract_eval: {e}", file=sys.stderr)
        return 2
    errors += more
    if errors:
        for e in errors:
            print(f"extract_eval: {e}", file=sys.stderr)
        return 1

    s = score(predicted, labeled)
    if args.json:
        print(json.dumps(s, indent=2))
    else:
        print(
            f"precision {_pct(s['precision'])} ({s['matched']}/{s['predicted']}), "
            f"recall {_pct(s['recall'])} ({s['matched']}/{s['labeled']}), "
            f"source errors {len(s['source_errors'])}"
        )
        for t, row in s["by_type"].items():
            print(f"  {t:14s} predicted {row['predicted']:3d}  labeled {row['labeled']:3d}  "
                  f"matched {row['matched']:3d}")  # fmt: skip
        for label in ("false_positives", "missed", "source_errors"):
            if s[label]:
                print(f"  {label.replace('_', ' ')}: {', '.join(s[label][:10])}")
    if args.min_precision is not None and (s["precision"] or 0) < args.min_precision:
        print(f"extract_eval: precision below {args.min_precision:.0%}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
