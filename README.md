# kicad-autolayout (working name)

Open-source automatic PCB placement and routing for KiCad. An LLM orchestrates; geometry and
optimization engines do the layout; KiCad's own DRC is the judge.

> **Status: phase 0 (foundation).** There is no placement or routing yet. What exists today is
> the groundwork every later phase is measured with: a lossless KiCad file reader/writer, a
> containerized `kicad-cli` DRC pipeline, and a regression corpus of open boards with
> high-speed interfaces (DDR, PCIe, USB3, ...).

## What works today

| Piece | What it does |
|---|---|
| `kal_ir::sexpr` (Rust) | Lossless S-expression tree for `.kicad_pcb` / `.kicad_sch`. Unchanged files write back byte-identical; numbers are never converted to floats; generated output uses a line-per-list canonical layout. |
| `kal-roundtrip` | CLI over the above: preserve mode (byte-identical) or `--canonical` (same tree after re-parse). |
| `docker/` | `kicad-cli pcb drc` runner on the official `kicad/kicad` images (9.0, 10.0). Logs the KiCad version, writes `drc.json` and a summary. |
| `orchestrator/drc_summary.py` | Turns a DRC JSON report into counts by severity/type plus the top items. |
| `orchestrator/drc_compare.py` | Checks that two DRC reports contain the same violations, ignoring metadata. |
| `bench/` | Smoke board, round-trip runner, external board corpus (37 boards) and its fetcher. |

## Design rules

The full list is in [`CLAUDE.md`](CLAUDE.md). The ones that shape the code:

- The LLM never outputs coordinates, tracks or vias, only schema-validated JSON (constraints, rules, floorplan hints, review notes).
- Final correctness is `kicad-cli pcb drc`. Any in-house DRC is only a fast pre-filter.
- Geometry uses integer nanometers, as KiCad does. There are no floats in the geometry core.
- Dependencies must be Apache-2.0 compatible; no GPL code is linked. GPL tools such as Freerouting run only as separate processes.
- No new code on SWIG/`pcbnew`. The tool talks to KiCad through IPC (`kipy`) or reads and writes files directly.
- Every run is reproducible: it logs the seed, engine version, KiCad version and ruleset hash.

```
KiCad GUI <-IPC(kipy)-> thin plugin <-> orchestrator service
orchestrator: LLM layer (constraints/rules/floorplan/review) -> engine core -> kicad-cli DRC loop
engine core (Rust): geometry + R-tree, placement (CP-SAT + SA), routing (Freerouting first, own router later)
```

## Repository layout

| Dir | What |
|---|---|
| `core/` | Rust engine: geometry, placement, routing (`kal-core`); placeholder for now |
| `ir/` | Board IR and KiCad file IO (`kal-ir`) |
| `orchestrator/` | Python: DRC tools now, LLM layer later |
| `plugin/` | Thin KiCad IPC plugin (planned) |
| `bench/` | Boards, corpus manifest, runners |
| `docker/` | DRC runner image |
| `docs/` | Design notes |

## Quick start

Requirements: Rust (the version is pinned in `rust-toolchain.toml`), Python 3.10+, and Docker for anything that runs KiCad.

```sh
# Build and test
cargo build
cargo test -q
python3 -m unittest discover -s orchestrator/tests -q
python3 -m unittest discover -s bench/tests -q

# DRC one board in Docker (KiCad 9.0 or 10.0)
docker build --build-arg KICAD_TAG=10.0 -f docker/Dockerfile -t kal-drc:10.0 .
docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp -v "$PWD:/work" \
  kal-drc:10.0 bench/boards/smoke/smoke.kicad_pcb out
# -> out/drc.json, out/summary.json, out/kicad_version.txt; exit 0 clean, 1 violations, 2 failure

# Round-trip one file
cargo run -q --bin kal-roundtrip -- board.kicad_pcb out.kicad_pcb              # byte-identical
cargo run -q --bin kal-roundtrip -- board.kicad_pcb out.kicad_pcb --canonical  # re-laid-out

# Round-trip + DRC compare over the external corpus
cargo build -q --release --bin kal-roundtrip
python3 bench/fetch_corpus.py bench/corpus/manifest.json corpus/external
bash bench/roundtrip.sh target/release/kal-roundtrip kal-drc:10.0 out/roundtrip corpus/external
# -> out/roundtrip/report.tsv
```

## CI

| Workflow | When | What |
|---|---|---|
| `ci.yml` | every PR, pushes to `main` | Rust fmt/clippy/tests, Python tests, DRC smoke test and KiCad demo round-trip on KiCad 9.0 and 10.0 |
| `corpus.yml` | manual, weekly, PRs touching `ir/`, `bench/`, `docker/` | external corpus round-trip and DRC compare, KiCad 9.0/10.0 × 4 shards |

## Board corpus

[`bench/corpus/manifest.json`](bench/corpus/manifest.json) lists 37 open KiCad boards with their
repo, license and interface tags. They are fetched at CI time and never committed. The boards cover:

- **Memory:** DDR3, DDR4, DDR5, LPDDR4 and LPDDR5.
- **PCIe:** M.2, OCuLink, x4/x8/x16 slots, Thunderbolt and a PCIe switch.
- **Other high-speed links:** USB 3.x, 10GbE/SFP+, MIPI CSI/DSI, LVDS, GMSL2, HDMI, DisplayPort and FPGA SerDes.

The boards are a regression and reference set, not training data. See
[`bench/corpus/README.md`](bench/corpus/README.md) for the coverage table, the gaps and the license policy.

## Roadmap

0. **Foundation** (now): IR, round-trip, DRC pipeline, corpus. Done when 100 open boards round-trip with zero diff and identical DRC.
1. **Rules and review**: datasheet to constraints to `.kicad_dru` and netclasses; LLM design review on a JSON board summary.
2. **Semi-auto placement**: decoupling and sub-circuits (CP-SAT), block floorplan, one-click Freerouting trial.
3. **End-to-end simple boards** (2–4 layers, ≤150 parts): own router, differential pairs, length tuning.
4. **Mid complexity** (4–6 layers, BGA fanout). High-speed DDR/RF/HDI stays assistant-only.

## License

[Apache License 2.0](LICENSE). Corpus boards are not part of this repository and keep their own
licenses, as listed in the manifest.
