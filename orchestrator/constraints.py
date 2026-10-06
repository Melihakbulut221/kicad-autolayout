#!/usr/bin/env python3
"""Validate and normalize design-constraint documents.

Constraints are what the LLM layer may produce (CLAUDE.md rule 1): typed JSON, never
geometry. Every constraint names its source (document + page) and is unusable until a human
approves it (rule 6). Lengths are given in millimetres and normalized to integer nanometres
(rule 3); values finer than 1 nm are rejected. Types and fields: docs/constraints.md.

Usage:
    python3 orchestrator/constraints.py constraints.json [--require-approved] [--json]
Exit: 0 valid, 1 invalid, 2 unreadable input.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from decimal import Decimal
from pathlib import Path

SCHEMA_VERSION = 1
NM_PER_MM = Decimal(1_000_000)
ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
# Reference designator, optionally with a pad: "C12", "U1.7", "J3.A12".
REF_RE = re.compile(r"^[A-Za-z]+[0-9]+[A-Za-z0-9_]*(\.[A-Za-z0-9_+-]+)?$")
COMMON_KEYS = {"id", "type", "source", "approved", "approved_by", "note"}


class Invalid(ValueError):
    """A constraint or the document breaks the schema."""


class FileError(Exception):
    """The constraints file cannot be read or is not JSON."""


def _number(c: dict, key: str) -> Decimal:
    v = c[key]
    if isinstance(v, bool) or not isinstance(v, (int, float, Decimal)):
        raise Invalid(f"'{key}' must be a number")
    d = Decimal(str(v))
    if not d.is_finite():
        raise Invalid(f"'{key}' must be finite")
    return d


def _mm(c: dict, key: str, *, required: bool = True, zero_ok: bool = False) -> int | None:
    """Read a millimetre field and return integer nanometres."""
    if key not in c:
        if required:
            raise Invalid(f"missing '{key}'")
        return None
    nm = _number(c, key) * NM_PER_MM
    if nm != nm.to_integral_value():
        raise Invalid(f"'{key}' is finer than 1 nm")
    if nm < 0 or (nm == 0 and not zero_ok):
        raise Invalid(f"'{key}' must be {'>= 0' if zero_ok else '> 0'}")
    return int(nm)


def _text(c: dict, key: str) -> str:
    v = c.get(key)
    if not isinstance(v, str) or not v.strip():
        raise Invalid(f"'{key}' must be a non-empty string")
    return v


def _nets(v: object, key: str, minimum: int = 1) -> list[str]:
    if (
        not isinstance(v, list)
        or len(v) < minimum
        or not all(isinstance(n, str) and n.strip() for n in v)
    ):
        raise Invalid(f"'{key}' must be a list of at least {minimum} net name(s)")
    if len(set(v)) != len(v):
        raise Invalid(f"'{key}' lists a net twice")
    return list(v)


def _selector(c: dict, key: str) -> dict:
    sel = c.get(key)
    if not isinstance(sel, dict) or len(sel) != 1 or not sel.keys() <= {"nets", "netclass"}:
        raise Invalid(f"'{key}' must be {{\"nets\": [...]}} or {{\"netclass\": \"...\"}}")
    if "nets" in sel:
        return {"nets": _nets(sel["nets"], f"{key}.nets")}
    return {"netclass": _text(sel, "netclass")}


def _ref(c: dict, key: str) -> str:
    v = _text(c, key)
    if not REF_RE.match(v):
        raise Invalid(f"'{key}' must be a reference like 'C12' or 'U1.7'")
    return v


def _clearance(c: dict) -> dict:
    out = {"a": _selector(c, "a"), "min_nm": _mm(c, "min_mm")}
    if "b" in c:
        out["b"] = _selector(c, "b")
    return out


def _track_width(c: dict) -> dict:
    vals = {k: _mm(c, f"{k}_mm", required=False) for k in ("min", "opt", "max")}
    given = [v for v in vals.values() if v is not None]
    if not given:
        raise Invalid("needs at least one of 'min_mm', 'opt_mm', 'max_mm'")
    if given != sorted(given):
        raise Invalid("needs min_mm <= opt_mm <= max_mm")
    out = {"on": _selector(c, "on")}
    out.update({f"{k}_nm": v for k, v in vals.items() if v is not None})
    return out


def _diff_pair(c: dict) -> dict:
    p, n = _text(c, "p"), _text(c, "n")
    if p == n:
        raise Invalid("'p' and 'n' must be different nets")
    out = {"p": p, "n": n, "width_nm": _mm(c, "width_mm"), "gap_nm": _mm(c, "gap_mm")}
    for key in ("max_uncoupled", "max_skew"):
        v = _mm(c, f"{key}_mm", required=False, zero_ok=True)
        if v is not None:
            out[f"{key}_nm"] = v
    return out


def _length_match(c: dict) -> dict:
    out = {
        "nets": _nets(c.get("nets"), "nets", minimum=2),
        "tolerance_nm": _mm(c, "tolerance_mm", zero_ok=True),
    }
    target = _mm(c, "target_mm", required=False)
    if target is not None:
        out["target_nm"] = target
    return out


def _max_length(c: dict) -> dict:
    return {"on": _selector(c, "on"), "max_nm": _mm(c, "max_mm")}


def _max_distance(c: dict) -> dict:
    return {"from": _ref(c, "from"), "to": _ref(c, "to"), "max_nm": _mm(c, "value_mm")}


def _impedance(c: dict) -> dict:
    ohms = _number(c, "ohms") if "ohms" in c else None
    if ohms is None or ohms <= 0:
        raise Invalid("'ohms' must be a number > 0")
    kind = c.get("kind")
    if kind not in ("single", "differential"):
        raise Invalid("'kind' must be 'single' or 'differential'")
    return {"on": _selector(c, "on"), "ohms": float(ohms), "kind": kind}


# type -> (allowed type-specific input fields, parser)
TYPES = {
    "clearance": ({"a", "b", "min_mm"}, _clearance),
    "track_width": ({"on", "min_mm", "opt_mm", "max_mm"}, _track_width),
    "diff_pair": ({"p", "n", "width_mm", "gap_mm", "max_uncoupled_mm", "max_skew_mm"}, _diff_pair),
    "length_match": ({"nets", "tolerance_mm", "target_mm"}, _length_match),
    "max_length": ({"on", "max_mm"}, _max_length),
    "max_distance": ({"from", "to", "value_mm"}, _max_distance),
    "impedance": ({"on", "ohms", "kind"}, _impedance),
}


def _source(c: dict) -> dict:
    src = c.get("source")
    if not isinstance(src, dict):
        raise Invalid("missing 'source' with 'doc' and 'page' (rule 6)")
    page = src.get("page")
    valid_page = (isinstance(page, int) and not isinstance(page, bool) and page >= 1) or (
        isinstance(page, str) and page.strip()
    )
    if not valid_page:
        raise Invalid("'source.page' must be a page number >= 1 or a non-empty string")
    out = {"doc": _text(src, "doc"), "page": page}
    if "section" in src:
        out["section"] = _text(src, "section")
    return out


def _constraint(c: object) -> dict:
    if not isinstance(c, dict):
        raise Invalid("must be an object")
    cid = _text(c, "id")
    if not ID_RE.match(cid):
        raise Invalid("'id' may only contain letters, digits, '_', '.' and '-'")
    ctype = c.get("type")
    if not isinstance(ctype, str) or ctype not in TYPES:
        raise Invalid(f"unknown type {ctype!r}; expected one of {', '.join(sorted(TYPES))}")
    keys, parse = TYPES[ctype]
    unknown = sorted(set(c) - COMMON_KEYS - keys)
    if unknown:
        raise Invalid(f"unknown field(s) for {ctype}: {', '.join(unknown)}")
    approved = c.get("approved", False)
    if not isinstance(approved, bool):
        raise Invalid("'approved' must be true or false")
    out = {"id": cid, "type": ctype, "source": _source(c), "approved": approved}
    if approved:
        out["approved_by"] = _text(c, "approved_by")
    if "note" in c:
        out["note"] = _text(c, "note")
    out.update(parse(c))
    return out


def validate(doc: object) -> tuple[list[dict], list[str]]:
    """Normalize a constraints document. Returns (constraints, errors); no errors = valid."""
    if not isinstance(doc, dict) or doc.get("version") != SCHEMA_VERSION:
        return [], [f'document must be an object with "version": {SCHEMA_VERSION}']
    items = doc.get("constraints")
    if not isinstance(items, list):
        return [], ["'constraints' must be a list"]
    out, errors, seen = [], [], set()
    for i, c in enumerate(items):
        label = f"constraints[{i}]"
        if isinstance(c, dict) and isinstance(c.get("id"), str):
            label += f" ({c['id']})"
        try:
            norm = _constraint(c)
        except Invalid as e:
            errors.append(f"{label}: {e}")
            continue
        if norm["id"] in seen:
            errors.append(f"{label}: duplicate id")
            continue
        seen.add(norm["id"])
        out.append(norm)
    return out, errors


def approved_only(constraints: list[dict]) -> list[dict]:
    """The constraints a human has approved: the only ones tools may act on (rule 6)."""
    return [c for c in constraints if c["approved"]]


def load_file(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)
    except OSError as e:
        raise FileError(f"cannot read {path}: {e.strerror}") from e
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise FileError(f"{path} is not valid JSON: {e}") from e


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("file", type=Path)
    p.add_argument(
        "--require-approved", action="store_true", help="fail if any constraint is not approved"
    )
    p.add_argument("--json", action="store_true", help="print the normalized constraints as JSON")
    args = p.parse_args(argv)

    try:
        doc = load_file(args.file)
    except FileError as e:
        print(f"constraints: {e}", file=sys.stderr)
        return 2

    constraints, errors = validate(doc)
    if args.require_approved:
        errors += [f"{c['id']}: not approved (rule 6)" for c in constraints if not c["approved"]]
    for e in errors:
        print(f"constraints: {e}", file=sys.stderr)
    if args.json:
        print(json.dumps({"version": SCHEMA_VERSION, "constraints": constraints}, indent=2))
    else:
        approved = sum(c["approved"] for c in constraints)
        print(f"{len(constraints)} valid ({approved} approved), {len(errors)} error(s)")
        for ctype, n in sorted(Counter(c["type"] for c in constraints).items()):
            print(f"  {n:4d}  {ctype}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
