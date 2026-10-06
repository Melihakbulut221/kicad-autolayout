#!/usr/bin/env python3
"""Pin the external corpus: record the commit each board's `ref` resolves to.

For every board without a `commit` (or every board with --refresh) the `ref` is resolved
through the GitHub API and written back to the manifest as `commit`. Each board's .kicad_pcb
paths are then checked to exist at that commit, so a typo in a new entry fails here and not
silently at fetch time. The manifest keeps its layout: one board per line.
Exit 0 all boards pinned and checked, 1 some failed (listed; those boards are left as they
were), 2 bad manifest or usage.

Usage:
    python3 bench/pin_corpus.py bench/corpus/manifest.json [--refresh] [--only ID ...]
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
from pathlib import Path

from fetch_corpus import ManifestError, http_get, load_manifest

API = "https://api.github.com/repos"


def resolve(repo: str, ref: str) -> str:
    url = f"{API}/{repo}/commits/{urllib.parse.quote(ref, safe='')}"
    return http_get(url, accept="application/vnd.github.sha").decode().strip()


def check_path(repo: str, commit: str, path: str) -> None:
    """Raise HTTPError 404 when `path` does not exist at `commit` (metadata only, no download)."""
    url = f"{API}/{repo}/contents/{urllib.parse.quote(path)}?ref={commit}"
    http_get(url, accept="application/vnd.github.object+json")


def format_manifest(data: dict) -> str:
    """One board per line, `commit` right after `ref`."""
    boards = []
    for b in data["boards"]:
        ordered = {}
        for k, v in b.items():
            if k == "commit":
                continue
            ordered[k] = v
            if k == "ref" and "commit" in b:
                ordered["commit"] = b["commit"]
        boards.append("    " + json.dumps(ordered, ensure_ascii=False))
    lines = ["{"]
    for k, v in data.items():
        if k != "boards":
            lines.append(f"  {json.dumps(k)}: {json.dumps(v, ensure_ascii=False)},")
    lines += ['  "boards": [', ",\n".join(boards), "  ]", "}"]
    return "\n".join(lines) + "\n"


def pin(data: dict, refresh: bool, only: list[str] | None, resolver=resolve, checker=check_path):
    """Pin boards in place; return (rows, failures) where rows are id/status/detail tuples."""
    rows, failures = [], 0
    for b in data["boards"]:
        if only is not None and b["id"] not in only:
            continue
        old = b.get("commit")
        try:
            commit = resolver(b["repo"], b["ref"]) if refresh or not old else old
            for path in b["pcb"]:
                checker(b["repo"], commit, path)
        except urllib.error.HTTPError as e:
            what = "missing path or ref" if e.code == 404 else f"HTTP {e.code}"
            rows.append((b["id"], "error", what))
            failures += 1
            continue
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            rows.append((b["id"], "error", str(e)))
            failures += 1
            continue
        b["commit"] = commit
        rows.append((b["id"], "same" if commit == old else "pinned", commit))
    return rows, failures


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("manifest", type=Path)
    p.add_argument("--refresh", action="store_true", help="re-resolve boards that are pinned")
    p.add_argument("--only", nargs="+", default=None, help="board ids to pin")
    args = p.parse_args(argv)

    try:
        load_manifest(args.manifest)
        data = json.loads(args.manifest.read_text(encoding="utf-8"))
    except ManifestError as e:
        print(f"pin_corpus: {e}", file=sys.stderr)
        return 2

    rows, failures = pin(data, args.refresh, args.only)
    args.manifest.write_text(format_manifest(data), encoding="utf-8")
    for row in rows:
        print("\t".join(row))
    print(f"pinned {len(rows) - failures}/{len(rows)} boards, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
