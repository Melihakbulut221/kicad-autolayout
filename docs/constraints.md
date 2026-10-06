# Design constraints (schema v1)

The only output the LLM layer may produce besides review notes (CLAUDE.md rule 1).
Validator: `orchestrator/constraints.py`. Example: `orchestrator/tests/fixtures/constraints_example.json`.

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

A **selector** is `{"nets": ["A", "B"]}` or `{"netclass": "DDR_DQ"}`.
A **reference** is a designator with an optional pad: `C12`, `U1.7`, `J3.A12`.

## Types
| type | fields | KiCad mapping (planned) |
|---|---|---|
| `clearance` | `a` selector, optional `b` selector, `min_mm` | `.kicad_dru` clearance rule |
| `track_width` | `on` selector, at least one of `min_mm` <= `opt_mm` <= `max_mm` | `.kicad_dru` track_width rule |
| `diff_pair` | `p`, `n` nets, `width_mm`, `gap_mm`, optional `max_uncoupled_mm`, `max_skew_mm` | `.kicad_dru` diff_pair_gap / track_width / diff_pair_uncoupled / skew |
| `length_match` | `nets` (>= 2), `tolerance_mm`, optional `target_mm` | `.kicad_dru` skew (and length when `target_mm`) |
| `max_length` | `on` selector, `max_mm` | `.kicad_dru` length max |
| `max_distance` | `from`, `to` references, `value_mm` | placement constraint for the engine (phase 2); no DRU equivalent |
| `impedance` | `on` selector, `ohms`, `kind` (`single` / `differential`) | needs the stackup to become widths/gaps; reported, not enforced |
