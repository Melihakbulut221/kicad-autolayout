#!/usr/bin/env python3
"""Print the lines of a layout guide that look like numeric layout rules, with their page.

Input is `pdftotext -layout` output (pages separated by form feeds). Only short matching lines
are printed, as `p<page>: <line>`, so a reviewer can find and cite rules without the document
being copied anywhere (the PDF itself is never committed; see bench/extraction/README.md).

Usage:
    pdftotext -layout guide.pdf - | python3 bench/extraction/rule_lines.py [--max 400]
"""

from __future__ import annotations

import argparse
import re
import sys

UNIT = r"(?:mm|mils?|inch(?:es)?|in\.|µm|um|Ω|ohms?|ps|ns|%|dB|GHz|MHz|nF|pF|µF|uF)"
RULE = re.compile(rf"\d+(?:\.\d+)?\s*(?:-|to|±|\+/-)?\s*\d*(?:\.\d+)?\s*{UNIT}(?![A-Za-z])", re.I)
WORDS = re.compile(
    r"impedance|skew|length|spacing|clearance|width|via|stub|match|mismatch|keep|distance|"
    r"gap|pair|reference plane|capacitor|placed|within|maximum|minimum|max|min",
    re.I,
)
# Table captions and column headers give the context (which interface, MIN/NOM/MAX) of a row.
CONTEXT = re.compile(r"^(?:Table|Figure)\s+\d+(?:-\d+)?\.?\s|\bMIN\b.*\bMAX\b|^\d+(?:\.\d+)*\s+[A-Z]")


def rule_lines(text: str, limit: int = 400) -> list[str]:
    out = []
    for page, body in enumerate(text.split("\f"), start=1):
        for raw in body.splitlines():
            line = " ".join(raw.split())
            if len(line) > 220:
                continue
            is_rule = RULE.search(line) and WORDS.search(line)
            if not is_rule and not CONTEXT.search(line):
                continue
            out.append(f"p{page}: {line}")
            if len(out) >= limit:
                return out
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--max", type=int, default=400)
    args = p.parse_args(argv)
    for line in rule_lines(sys.stdin.read(), args.max):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
