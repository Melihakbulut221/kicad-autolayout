#!/usr/bin/env python3
"""Compare the violations in two `kicad-cli pcb drc --format json` reports.

Report metadata (date, source, kicad_version) is ignored; violations are compared as
multisets per section. Some entries are compared without their items, because KiCad picks
the items or the marker position arbitrarily and does not reproduce the pick between runs on
the same file: unconnected items (which of several equally near pads), silkscreen overlap and
copper connection width (where along the overlap or narrow neck). Their count, type, severity
and description still have to match. Exit 0 identical, 1 different, 2 bad input.

Usage:
    python3 orchestrator/drc_compare.py a/drc.json b/drc.json [--top 10]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from drc_summary import SECTIONS, DrcReportError, load_report

# Violation types whose items/positions are an arbitrary pick (see module doc).
ARBITRARY_ITEMS = {"silk_overlap", "connection_width"}


def violation_key(v: dict, with_items: bool = True) -> tuple:
    items = tuple(
        (i.get("description", ""), json.dumps(i.get("pos"), sort_keys=True))
        for i in (v.get("items") or [])
        if with_items
    )
    return (
        v.get("type", ""),
        v.get("severity", ""),
        bool(v.get("excluded")),
        v.get("description", ""),
        items,
    )


def compare(a: dict, b: dict) -> dict:
    """Per differing section: (only in a, only in b) as Counters of violation keys."""
    diff = {}
    for name in SECTIONS:

        def key(v: dict) -> tuple:
            arbitrary = name == "unconnected_items" or v.get("type") in ARBITRARY_ITEMS
            return violation_key(v, not arbitrary)

        ca = Counter(key(v) for v in a.get(name) or [])
        cb = Counter(key(v) for v in b.get(name) or [])
        if ca != cb:
            diff[name] = (ca - cb, cb - ca)
    return diff


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("a", type=Path)
    p.add_argument("b", type=Path)
    p.add_argument("--top", type=int, default=10, help="differences listed per side (default 10)")
    args = p.parse_args(argv)

    try:
        a, b = load_report(args.a), load_report(args.b)
    except DrcReportError as e:
        print(f"drc_compare: {e}", file=sys.stderr)
        return 2

    diff = compare(a, b)
    if not diff:
        print("identical")
        return 0
    for name, (only_a, only_b) in diff.items():
        print(f"{name}: {sum(only_a.values())} only in a, {sum(only_b.values())} only in b")
        for sign, counter in (("-", only_a), ("+", only_b)):
            for (vtype, severity, _, desc, _), n in counter.most_common(max(args.top, 0)):
                print(f"  {sign}{n} [{severity}] {vtype}: {desc}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
