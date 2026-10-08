# Labeled extraction set

Ground truth for `orchestrator/extract_eval.py` (phase 1 target: extraction precision >= 90%).
One extraction task = one source document + one board net list; the expected output is the
labeled constraint file for that pair.

| file | content |
|---|---|
| `sources.json` | documents: URL, title, page count, sha256 of the fetched PDF, board used with it |
| `boards/<board>.json` | synthetic net list given to the extractor together with the document |
| `labeled/<source id>.json` | expected constraints (schema v1, `docs/constraints.md`); `not_labeled` lists rules left out and why |

Status: **draft, not reviewed.** Every constraint is `"approved": false`. Drafted by Claude from
the rule lines printed by the `Extraction sources` workflow; a human must check each one against
the cited page, fix it, and only then set `approved: true` with `approved_by`.

## Conventions
- `source.doc` is the source id, `source.page` the PDF page index (equal to the printed page
  number in these documents).
- mils are converted exactly (1 mil = 0.0254 mm).
- Impedance uses the TYP value of a MIN/TYP/MAX row; length limits use the MAX column, spacing
  rows the MIN column. `note` says which column was assumed where the printed row is ambiguous.
- Center-to-center spacing in multiples of the trace width w becomes an edge clearance of
  (n - 1) * w.
- Rules with no schema v1 type (plane-edge distance, via stubs, break-out length, placement
  windows, value ranges) are listed in `not_labeled`, not forced into another type.

## Review checklist
1. Open the PDF (URL in `sources.json`, compare sha256) at the cited page.
2. Check the value, unit, column (MIN/TYP/MAX) and which nets the row applies to.
3. Check `not_labeled`: anything there that should be a constraint?
4. Set `approved: true`, `approved_by: <name>`; add missing rules as new constraints.

The PDFs are never committed. `Extraction sources` (`.github/workflows/extraction-sources.yml`)
fetches them in CI and prints only short rule lines with page numbers
(`bench/extraction/rule_lines.py`).
