#!/usr/bin/env python3
"""Summarize a `kicad-cli pcb drc --format json` report.

Never print the raw report; print counts by section/severity/type and the top items.
Exit code: 0 = no active violations at or above --fail-on, 1 = violations, 2 = bad input.

Usage:
    python3 orchestrator/drc_summary.py out/drc.json [--top 10] [--json] [--fail-on error]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

SECTIONS = ("violations", "unconnected_items", "schematic_parity")
SEVERITY_RANK = {"ignore": 0, "info": 1, "action": 1, "warning": 2, "error": 3}


class DrcReportError(ValueError):
    """The input is not a readable DRC JSON report."""


def load_report(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as e:
        raise DrcReportError(f"cannot read {path}: {e.strerror}") from e
    except json.JSONDecodeError as e:
        raise DrcReportError(f"{path} is not valid JSON: {e}") from e
    if not isinstance(data, dict) or not any(k in data for k in SECTIONS):
        raise DrcReportError(f"{path} has none of {', '.join(SECTIONS)}")
    return data


def _is_excluded(v: dict) -> bool:
    # `(severity exclusion)` custom rules may appear without the `excluded` key (KiCad bug).
    return bool(v.get("excluded")) or v.get("severity") == "exclusion"


def _first_pos(v: dict) -> str:
    for item in v.get("items") or []:
        pos = item.get("pos")
        if isinstance(pos, dict) and "x" in pos and "y" in pos:
            return f"({pos['x']}, {pos['y']})"
    return ""


def summarize(report: dict, top: int = 10) -> dict:
    sections = {}
    active_by_severity: Counter = Counter()
    for name in SECTIONS:
        entries = report.get(name) or []
        active = [v for v in entries if not _is_excluded(v)]
        by_type = Counter(v.get("type", "?") for v in active)
        by_severity = Counter(v.get("severity", "?") for v in active)
        active_by_severity.update(by_severity)
        sections[name] = {
            "total": len(entries),
            "excluded": len(entries) - len(active),
            "by_severity": dict(by_severity.most_common()),
            "by_type": dict(by_type.most_common()),
            "top": [
                {
                    "type": v.get("type", "?"),
                    "severity": v.get("severity", "?"),
                    "description": v.get("description", ""),
                    "items": [i.get("description", "") for i in (v.get("items") or [])],
                    "pos": _first_pos(v),
                }
                for v in sorted(
                    active,
                    key=lambda v: -SEVERITY_RANK.get(v.get("severity", ""), 0),
                )[:top]
            ],
        }
    return {
        "source": report.get("source", ""),
        "kicad_version": report.get("kicad_version", ""),
        "coordinate_units": report.get("coordinate_units", ""),
        "active_by_severity": dict(active_by_severity),
        "sections": sections,
    }


def count_at_or_above(summary: dict, level: str) -> int:
    floor = SEVERITY_RANK[level]
    return sum(
        n for sev, n in summary["active_by_severity"].items() if SEVERITY_RANK.get(sev, 0) >= floor
    )


def format_text(summary: dict) -> str:
    out = [
        f"DRC {summary['source'] or '?'} (KiCad {summary['kicad_version'] or '?'}, "
        f"units {summary['coordinate_units'] or '?'})"
    ]
    for name, s in summary["sections"].items():
        if s["total"] == 0:
            out.append(f"{name}: 0")
            continue
        sev = ", ".join(f"{k} {v}" for k, v in s["by_severity"].items()) or "none active"
        out.append(f"{name}: {s['total']} ({sev}; excluded {s['excluded']})")
        for t, n in s["by_type"].items():
            out.append(f"  {n:5d}  {t}")
        if s["top"]:
            out.append("  top:")
            for v in s["top"]:
                items = "; ".join(i for i in v["items"] if i)[:120]
                pos = f" @ {v['pos']}" if v["pos"] else ""
                out.append(f"    [{v['severity']}] {v['type']}{pos}: {v['description']}")
                if items:
                    out.append(f"        {items}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("report", type=Path)
    p.add_argument("--top", type=int, default=10, help="items listed per section (default 10)")
    p.add_argument("--json", action="store_true", help="print the summary as JSON")
    p.add_argument(
        "--fail-on",
        choices=["error", "warning", "never"],
        default="error",
        help="exit 1 if active violations at or above this severity exist (default error)",
    )
    args = p.parse_args(argv)

    try:
        summary = summarize(load_report(args.report), top=max(args.top, 0))
    except DrcReportError as e:
        print(f"drc_summary: {e}", file=sys.stderr)
        return 2

    print(json.dumps(summary, indent=2) if args.json else format_text(summary))
    if args.fail_on != "never" and count_at_or_above(summary, args.fail_on) > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
