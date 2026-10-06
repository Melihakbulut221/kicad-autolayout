#!/usr/bin/env python3
"""Fetch the external board corpus listed in bench/corpus/manifest.json.

Boards are downloaded at CI time from GitHub and never committed. For each board the
.kicad_pcb file(s) plus same-stem .kicad_pro/.kicad_dru (when present) are saved to
<out>/<id>/, at the commit `ref` resolves to (or the pinned `commit`). Resolved commits go
to <out>/lock.json, per-board status to <out>/fetch.tsv.
Exit 0 all fetched, 1 some failed (listed), 2 bad manifest or usage.

Usage:
    python3 bench/fetch_corpus.py bench/corpus/manifest.json corpus/external [--shard 0/4]
        [--only ID ...]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REQUIRED = ("id", "repo", "ref", "pcb", "license", "interfaces")
INTERFACES = {
    "ddr3", "ddr4", "ddr5", "lpddr4", "lpddr5",
    "pcie", "thunderbolt",
    "usb2-hs", "usb3", "usb-c",
    "gbe", "10gbe",
    "hdmi", "displayport", "mipi-csi", "mipi-dsi", "lvds", "gmsl",
    "serdes", "rf", "si-test",
}  # fmt: skip
SIDECARS = (".kicad_pro", ".kicad_dru")


class ManifestError(ValueError):
    """The manifest or a command-line selection is invalid."""


def load_manifest(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ManifestError(f"cannot read {path}: {e}") from e
    boards = data.get("boards") if isinstance(data, dict) else None
    if not isinstance(boards, list) or not boards:
        raise ManifestError(f"{path}: expected a non-empty 'boards' list")
    seen = set()
    for b in boards:
        bid = b.get("id", "?") if isinstance(b, dict) else "?"
        missing = [k for k in REQUIRED if not isinstance(b, dict) or k not in b]
        if missing:
            raise ManifestError(f"{bid}: missing {', '.join(missing)}")
        if bid in seen:
            raise ManifestError(f"duplicate id {bid}")
        seen.add(bid)
        pcbs = b["pcb"]
        if not isinstance(pcbs, list) or not pcbs or not all(
            isinstance(p, str) and p.endswith(".kicad_pcb") for p in pcbs
        ):
            raise ManifestError(f"{bid}: 'pcb' must be a non-empty list of .kicad_pcb paths")
        unknown = set(b["interfaces"]) - INTERFACES
        if unknown:
            raise ManifestError(f"{bid}: unknown interfaces {sorted(unknown)}")
    return sorted(boards, key=lambda b: b["id"])


def parse_shard(text: str) -> tuple[int, int]:
    try:
        i, n = (int(x) for x in text.split("/"))
    except ValueError:
        raise ManifestError(f"bad --shard {text!r}, expected i/n") from None
    if n < 1 or not 0 <= i < n:
        raise ManifestError(f"bad --shard {text!r}, need 0 <= i < n")
    return i, n


def select(boards: list[dict], i: int, n: int, only: list[str] | None) -> list[dict]:
    return [
        b for k, b in enumerate(boards) if k % n == i and (only is None or b["id"] in only)
    ]


def http_get(url: str, accept: str | None = None) -> bytes:
    headers = {"User-Agent": "kicad-autolayout-corpus"}
    if accept:
        headers["Accept"] = accept
    token = os.environ.get("GITHUB_TOKEN")
    if token and url.startswith("https://api.github.com/"):
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if e.code == 404 or attempt == 2:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == 2:
                raise
        time.sleep(2 ** (attempt + 1))
    raise AssertionError("unreachable")


def fetch_board(board: dict, out: Path) -> dict:
    repo = board["repo"]
    commit = board.get("commit")
    if not commit:
        ref = urllib.parse.quote(board["ref"], safe="")
        url = f"https://api.github.com/repos/{repo}/commits/{ref}"
        commit = http_get(url, accept="application/vnd.github.sha").decode().strip()
    dest = out / board["id"]
    dest.mkdir(parents=True, exist_ok=True)
    files = []
    for pcb in board["pcb"]:
        stem = pcb[: -len(".kicad_pcb")]
        for path, required in [(pcb, True)] + [(stem + ext, False) for ext in SIDECARS]:
            url = f"https://raw.githubusercontent.com/{repo}/{commit}/{urllib.parse.quote(path)}"
            try:
                data = http_get(url)
            except urllib.error.HTTPError as e:
                if e.code == 404 and not required:
                    continue
                raise
            (dest / Path(path).name).write_bytes(data)
            files.append(path)
    return {"id": board["id"], "repo": repo, "ref": board["ref"], "commit": commit, "files": files}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("manifest", type=Path)
    p.add_argument("out", type=Path)
    p.add_argument("--shard", default="0/1", help="i/n: fetch boards whose index %% n == i")
    p.add_argument("--only", nargs="+", default=None, help="board ids to fetch")
    args = p.parse_args(argv)

    try:
        boards = load_manifest(args.manifest)
        i, n = parse_shard(args.shard)
    except ManifestError as e:
        print(f"fetch_corpus: {e}", file=sys.stderr)
        return 2

    selected = select(boards, i, n, args.only)
    args.out.mkdir(parents=True, exist_ok=True)
    locks, rows = [], ["id\tstatus\tdetail"]
    for b in selected:
        try:
            lock = fetch_board(b, args.out)
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            rows.append(f"{b['id']}\terror\t{e}")
            print(f"fetch_corpus: {b['id']}: {e}", file=sys.stderr)
            continue
        locks.append(lock)
        rows.append(f"{b['id']}\tok\t{lock['commit']}")
    (args.out / "lock.json").write_text(json.dumps(locks, indent=2) + "\n")
    (args.out / "fetch.tsv").write_text("\n".join(rows) + "\n")
    print(f"fetched {len(locks)}/{len(selected)} boards (shard {args.shard})")
    return 0 if len(locks) == len(selected) else 1


if __name__ == "__main__":
    sys.exit(main())
