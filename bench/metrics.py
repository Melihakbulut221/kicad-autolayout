#!/usr/bin/env python3
"""Benchmark metrics per board, from a board summary and a DRC summary.

One metrics row combines `kal-summary` output (schema kal-board-summary/1) with the
`summary.json` that docker/drc.sh writes (drc_summary --json). Lengths stay integer nm
(CLAUDE.md rule 3). For the human-routed corpus these rows are the reference the engine is
measured against later (DRC errors, unconnected, wirelength, vias, board size).

Usage:
    python3 bench/metrics.py row <board-summary.json> <drc-summary.json> [--id ID]
    python3 bench/metrics.py collect <kal-summary> <roundtrip out dir> [-o out/metrics]
        reads every <out>/<board>/board.path written by bench/roundtrip.sh, runs kal-summary
        on the board and pairs it with <out>/<board>/drc-orig/summary.json; writes
        <prefix>.jsonl, <prefix>.tsv and a Markdown table on stdout
Exit 0 ok, 1 some boards could not be summarized (listed, rows still written), 2 bad usage.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

COLUMNS = (
    "id",
    "kicad",
    "layers",
    "footprints",
    "pads",
    "nets",
    "routed_nets",
    "segments",
    "arcs",
    "vias",
    "zones",
    "track_length_nm",
    "board_w_nm",
    "board_h_nm",
    "drc_errors",
    "drc_warnings",
    "unconnected",
)


def board_metrics(summary: dict) -> dict:
    counts = summary.get("counts", {})
    lengths = summary.get("segment_length_nm", {})
    nets = [n for n in summary.get("nets", []) if n]
    outline = summary.get("outline_nm")
    w = h = None
    if isinstance(outline, list) and len(outline) == 4:
        w, h = int(outline[2]) - int(outline[0]), int(outline[3]) - int(outline[1])
    return {
        "layers": len(summary.get("copper_layers", [])),
        "footprints": counts.get("footprints"),
        "pads": counts.get("pads"),
        "nets": len(nets),
        "routed_nets": sum(1 for n, v in lengths.items() if n and int(v) > 0),
        "segments": counts.get("segments"),
        "arcs": counts.get("arcs"),
        "vias": counts.get("vias"),
        "zones": counts.get("zones"),
        "track_length_nm": sum(int(v) for v in lengths.values()),
        "board_w_nm": w,
        "board_h_nm": h,
    }


def drc_metrics(drc: dict | None) -> dict:
    if drc is None:
        return {"kicad": None, "drc_errors": None, "drc_warnings": None, "unconnected": None}
    severity = drc.get("active_by_severity", {})
    unconnected = drc.get("sections", {}).get("unconnected_items", {})
    return {
        "kicad": drc.get("kicad_version") or None,
        "drc_errors": severity.get("error", 0),
        "drc_warnings": severity.get("warning", 0),
        "unconnected": unconnected.get("total", 0) - unconnected.get("excluded", 0),
    }


def row(board_id: str, summary: dict, drc: dict | None) -> dict:
    merged = {"id": board_id, **board_metrics(summary), **drc_metrics(drc)}
    return {k: merged.get(k) for k in COLUMNS}


def tsv(rows: list[dict]) -> str:
    lines = ["\t".join(COLUMNS)]
    for r in rows:
        lines.append("\t".join("" if r[c] is None else str(r[c]) for c in COLUMNS))
    return "\n".join(lines) + "\n"


def markdown(rows: list[dict]) -> str:
    cols = (
        "id", "layers", "footprints", "nets", "vias", "track_length_nm", "drc_errors", "unconnected",
    )  # fmt: skip
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in rows:
        out.append("| " + " | ".join("" if r[c] is None else str(r[c]) for c in cols) + " |")
    return "\n".join(out) + "\n"


def load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def collect(kal_summary: Path, out: Path) -> tuple[list[dict], list[str]]:
    rows, failed = [], []
    for d in sorted(p for p in out.iterdir() if (p / "board.path").is_file()):
        board = Path((d / "board.path").read_text(encoding="utf-8").strip())
        # External corpus boards live in <...>/external/<manifest id>/<file>.kicad_pcb.
        external = board.parent.parent.name == "external"
        board_id = board.parent.name if external else str(board.with_suffix(""))
        res = subprocess.run([str(kal_summary), str(board)], capture_output=True, text=True)
        try:
            summary = json.loads(res.stdout) if res.returncode == 0 else None
        except json.JSONDecodeError:
            summary = None
        if summary is None:
            failed.append(str(board))
            continue
        rows.append(row(board_id, summary, load_json(d / "drc-orig" / "summary.json")))
    return rows, failed


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("row", help="one metrics row as JSON")
    r.add_argument("summary", type=Path)
    r.add_argument("drc", type=Path)
    r.add_argument("--id", default=None)
    c = sub.add_parser("collect", help="metrics for every board in a roundtrip.sh out dir")
    c.add_argument("kal_summary", type=Path)
    c.add_argument("out", type=Path)
    c.add_argument("-o", "--prefix", type=Path, default=Path("out/metrics"))
    args = p.parse_args(argv)

    if args.cmd == "row":
        summary = load_json(args.summary)
        if summary is None:
            print(f"metrics: cannot read {args.summary}", file=sys.stderr)
            return 2
        print(json.dumps(row(args.id or args.summary.stem, summary, load_json(args.drc))))
        return 0

    if not args.out.is_dir():
        print(f"metrics: {args.out} is not a directory", file=sys.stderr)
        return 2
    rows, failed = collect(args.kal_summary, args.out)
    args.prefix.parent.mkdir(parents=True, exist_ok=True)
    jsonl = "".join(json.dumps(x) + "\n" for x in rows)
    args.prefix.with_suffix(".jsonl").write_text(jsonl, encoding="utf-8")
    args.prefix.with_suffix(".tsv").write_text(tsv(rows), encoding="utf-8")
    sys.stdout.write(markdown(rows))
    for f in failed:
        print(f"metrics: kal-summary failed on {f}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
