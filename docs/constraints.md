# Design constraints (schema v1)

The only output the LLM layer may produce besides review notes (CLAUDE.md rule 1).
Validator: `orchestrator/constraints.py`. Rules generator: `orchestrator/dru.py`. Netclasses:
`orchestrator/netclass.py`.
Example: `orchestrator/tests/fixtures/constraints_example.json`.

```json
{"version": 1, "constraints": [
  {"id": "c12-near-u1", "type": "max_distance", "from": "C12", "to": "U1.7", "value_mm": 2.0,
   "source": {"doc": "pmic-datasheet.pdf", "page": 14}, "approved": false}
]}
```

## Common fields
| field | rule |
|---|---|
| `id` | unique, `[A-Za-z0-9_.-]+` |
| `type` | one of the types below |
| `source` | required: `doc` (string), `page` (int >= 1 or string such as "Table 3"), optional `section` (rule 6) |
| `approved` | bool, default false; tools act only on approved constraints |
| `approved_by` | required when `approved` is true |
| `note` | optional |

Unknown fields are errors. Lengths are in mm and normalized to integer nm (`*_mm` -> `*_nm`);
values finer than 1 nm are rejected.

A **selector** is `{"nets": ["A", "B"]}` or `{"netclass": "DDR_DQ"}`. Names must match the
board exactly (hierarchical nets include their path, e.g. `/DDR/DQ0`).
A **reference** is a designator with an optional pad: `C12`, `U1.7`, `J3.A12`.

## Types and KiCad mapping
`dru.py` writes one rule per approved constraint, named `kal:<id>`, with a comment naming the
source and approver. Selectors become `A.NetName == '...'` / `A.NetClass == '...'` conditions.

| type | fields | `.kicad_dru` |
|---|---|---|
| `clearance` | `a` selector, optional `b` selector, `min_mm` | `clearance (min)`; `b` adds a `B.` condition |
| `track_width` | `on` selector, at least one of `min_mm` <= `opt_mm` <= `max_mm` | `track_width (min/opt/max)` |
| `diff_pair` | `p`, `n` nets, `width_mm`, `gap_mm`, optional `max_uncoupled_mm`, `max_skew_mm` | `track_width (opt)`, `diff_pair_gap (opt)`, `diff_pair_uncoupled (max)`, `skew (max)` |
| `length_match` | `nets` (>= 2), `tolerance_mm`, optional `target_mm` | `skew (max tolerance)`; with target also `length (min target-tol) (max target+tol)` |
| `max_length` | `on` selector, `max_mm` | `length (max)` |
| `max_distance` | `from`, `to` references, `value_mm` | none: placement constraint for the engine (phase 2) |
| `impedance` | `on` selector, `ohms`, `kind` (`single` / `differential`) | none yet: needs the stackup to become widths/gaps |
| `netclass` | `name` (not `Default`), `patterns` (KiCad netclass patterns, e.g. `DDR_DQ*`), at least one of `clearance_mm`, `track_width_mm`, `via_diameter_mm`, `via_drill_mm` (< diameter), `diff_pair_width_mm`, `diff_pair_gap_mm` | none: `netclass.py` writes it to the `.kicad_pro` |

Diff pair width and gap are routing targets (`opt`), not DRC minimums; impedance will be checked
separately once stackups are in the IR.

## Netclasses
`python3 orchestrator/netclass.py constraints.json board.kicad_pro [-o out.kicad_pro]` merges every
approved `netclass` into `net_settings`: the class goes in `classes` (fields not given are copied
from the project's Default class), its patterns in `netclass_patterns`. A class or patterns of the
same name are replaced, the rest of the project is kept. A `{"netclass": ...}` selector in other
constraints can then name it. KiCad checks netclass clearance in DRC; netclass track width and via
sizes are routing defaults, so minimums belong in `track_width` constraints.

## Extraction scoring
`python3 orchestrator/extract_eval.py predicted.json labeled.json [--min-precision 0.9]` scores LLM
output against a human-labeled constraint file for the same datasheet. A prediction counts when
type and all type-specific fields equal a labeled constraint after normalization (nm values; net
sets without order); ids, approval and notes are ignored, a wrong `source.page` is reported as a
source error. Phase 1 target: precision >= 90%.
