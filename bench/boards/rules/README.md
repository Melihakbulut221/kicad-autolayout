# rules

Test board for `orchestrator/dru.py`. Two parallel F.Cu tracks, 0.25 mm wide, nets `HV1` and
`GND`, 0.35 mm edge gap. With KiCad defaults (0.2 mm clearance, no minimum width) DRC reports
no clearance or track_width errors. With the rules generated from `constraints.json`
(`HV1` clearance 0.5 mm, `HV1` width >= 0.3 mm) both must appear, which proves KiCad loaded
and applied the generated `.kicad_dru`. Checked in the CI `drc` job on KiCad 9.0 and 10.0.
