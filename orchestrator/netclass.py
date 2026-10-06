#!/usr/bin/env python3
"""Write netclass definitions from approved constraints into a KiCad project (.kicad_pro).

Only approved `netclass` constraints are used (CLAUDE.md rule 6). Each one becomes a class in
`net_settings.classes` plus its patterns in `net_settings.netclass_patterns`; a class or
pattern of the same name already in the project is replaced, everything else is kept. Fields
the constraint leaves out are copied from the project's Default class. Sizes are integer nm
internally and written as exact mm numbers, which is how KiCad stores them (rule 3 applies to
the geometry core; the project file is KiCad's format). The ruleset hash is printed (rule 7).

Usage:
    python3 orchestrator/netclass.py constraints.json board.kicad_pro [-o out.kicad_pro]
    (without -o the project is updated in place)
Exit: 0 ok, 1 invalid constraints, 2 unreadable input.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from decimal import Decimal
from pathlib import Path

import constraints as cs
from dru import ruleset_hash

# KiCad's Default class when the project has no net_settings yet (net settings schema 3; KiCad
# 9 and 10 migrate it and add class priorities on load).
DEFAULT_CLASS = {
    "bus_width": 12,
    "clearance": 0.2,
    "diff_pair_gap": 0.25,
    "diff_pair_via_gap": 0.25,
    "diff_pair_width": 0.2,
    "line_style": 0,
    "microvia_diameter": 0.3,
    "microvia_drill": 0.1,
    "name": "Default",
    "pcb_color": "rgba(0, 0, 0, 0.000)",
    "schematic_color": "rgba(0, 0, 0, 0.000)",
    "track_width": 0.2,
    "via_diameter": 0.6,
    "via_drill": 0.3,
    "wire_width": 6,
}
NET_SETTINGS = {
    "classes": [DEFAULT_CLASS],
    "meta": {"version": 3},
    "net_colors": None,
    "netclass_assignments": None,
    "netclass_patterns": [],
}


class Conflict(ValueError):
    """Two approved netclass constraints define the same class."""


def mm(nm: int) -> int | float:
    """Integer nanometres as an exact mm JSON number, e.g. 127000 -> 0.127, 2000000 -> 2."""
    d = Decimal(nm).scaleb(-6)
    return int(d) if d == d.to_integral_value() else float(d)


def apply(project: dict, approved: list[dict]) -> list[str]:
    """Merge the approved netclass constraints into `project` in place; returns class names."""
    classes = [c for c in approved if c["type"] == "netclass"]
    names = [c["name"] for c in classes]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        raise Conflict(f"netclass defined more than once: {', '.join(dupes)}")
    if not classes:
        return []

    net = project.get("net_settings") or copy.deepcopy(NET_SETTINGS)
    project["net_settings"] = net
    existing = net.get("classes") or []
    default = next((k for k in existing if k.get("name") == "Default"), None)
    if default is None:
        default = copy.deepcopy(DEFAULT_CLASS)
        existing.insert(0, default)
    kept = [k for k in existing if k.get("name") not in names]
    for c in classes:
        k = {key: v for key, v in default.items() if key != "priority"}
        k["name"] = c["name"]
        for size in cs.NETCLASS_SIZES:
            if f"{size}_nm" in c:
                k[size] = mm(c[f"{size}_nm"])
        kept.append(k)
    if "priority" in default:
        # KiCad 9+: lower number wins; Default stays last.
        for i, k in enumerate(x for x in kept if x.get("name") != "Default"):
            k["priority"] = i
    net["classes"] = kept

    patterns = [p for p in net.get("netclass_patterns") or [] if p.get("netclass") not in names]
    patterns += [{"netclass": c["name"], "pattern": p} for c in classes for p in c["patterns"]]
    net["netclass_patterns"] = patterns
    return names


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("constraints", type=Path)
    p.add_argument("project", type=Path)
    p.add_argument("-o", "--output", type=Path, help="write here (default: update the project)")
    args = p.parse_args(argv)

    try:
        doc = cs.load_file(args.constraints)
        project = json.loads(args.project.read_text(encoding="utf-8"))
    except cs.FileError as e:
        print(f"netclass: {e}", file=sys.stderr)
        return 2
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
        print(f"netclass: cannot read project {args.project}: {e}", file=sys.stderr)
        return 2
    if not isinstance(project, dict):
        print(f"netclass: {args.project} is not a KiCad project", file=sys.stderr)
        return 2
    constraints, errors = cs.validate(doc)
    if errors:
        for e in errors:
            print(f"netclass: {e}", file=sys.stderr)
        return 1

    approved = [c for c in cs.approved_only(constraints) if c["type"] == "netclass"]
    try:
        names = apply(project, approved)
    except Conflict as e:
        print(f"netclass: {e}", file=sys.stderr)
        return 1
    out = args.output or args.project
    out.write_text(json.dumps(project, indent=2) + "\n", encoding="utf-8")
    print(f"netclass: {len(names)} class(es) written to {out}", file=sys.stderr)
    print(f"netclass: ruleset sha256 {ruleset_hash(approved)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
