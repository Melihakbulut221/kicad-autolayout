# CLAUDE.md — kicad-autolayout (working name)

Product: automatic PCB placement/routing for KiCad. LLM = orchestrator only. Geometry/optimization engines do the layout. KiCad's own DRC is the judge. The whole project (engine, plugin, orchestrator) is open source under Apache-2.0 in a public repo.

## Hard rules (never break)
1. LLM never outputs coordinates, tracks or vias. LLM outputs only schema-validated JSON (constraints, rules, floorplan hints, review notes).
2. Final correctness = `kicad-cli pcb drc --format json --refill-zones`. Own DRC is a fast conservative pre-filter only.
3. Internal unit = integer nanometers (matches KiCad). No floats in the geometry core.
4. License is Apache-2.0. Dependencies must be Apache-2.0 compatible (MIT, Apache-2.0, BSD, BSL-1.0, ISC, Zlib); no GPL/LGPL/AGPL code linked or vendored. GPL tools (Freerouting) run only as a separate process (CLI/REST).
5. No new code on SWIG/`pcbnew` (removed in KiCad 11). Use IPC (`kipy`, MIT) or file-level S-expression IO.
6. Every datasheet-derived constraint carries a source (doc + page) and needs human approval before use.
7. Deterministic runs: log seed, engine version, KiCad version, ruleset hash.

## Architecture
```
KiCad GUI <-IPC(kipy)-> thin plugin <-> orchestrator service
orchestrator: LLM layer (constraints/rules/floorplan/review) -> engine core -> kicad-cli DRC loop
engine core (Rust): Clipper2 + R-tree, placement (CP-SAT + SA), routing (Freerouting first, own router later)
server side (no GUI): S-expression read/write + kicad-cli. Desktop: kipy.
```
Own IR (JSON/protobuf): footprints, pads, nets, netclasses, rules, stackup. Both KiCad paths fill the IR. Keep IR independent of KiCad version.

## Stack (decided)
- Core: Rust (cargo workspace: `core` = kal-core, `ir` = kal-ir). Python only for orchestration, prototypes, evaluators.
- Geometry: Clipper2 (BSL-1.0), rstar or Boost R-tree. Shapely/GEOS only in analysis/benchmarks. No CGAL (GPL).
- Placement: OR-Tools CP-SAT for constrained sub-problems (decoupling, connectors, keep-outs); simulated annealing for global; legalizer after.
- Routing: Freerouting (separate process, DSN/SES) -> own global (negotiated congestion) + detailed (gridless A*, rip-up/reroute) router in phase 3.
- File IO: own lossless S-expression tree in Rust (`kal_ir::sexpr`, no third-party parser; kiutils is GPL-3.0). Unchanged nodes keep their original bytes; generated nodes use the canonical layout.
- Constraints: schema v1 in `docs/constraints.md`, validator `orchestrator/constraints.py`, `.kicad_dru` generator `orchestrator/dru.py` (stdlib only). mm in, integer nm out.
- Board summary for the LLM review: `kal_ir::board` (schema `kal-board-summary/1`), hand-written JSON, no serde (no new crates without a lockfile update in CI).
- Write boards with line breaks (kicad-cli 10.0.x fails on very large single-line files).

## Repo layout (proposed)
```
/core        engine (geometry, placement, routing)
/ir          schema + converters
/orchestrator LLM layer, constraint extraction, DRC loop
/plugin      kipy plugin (executable runtime, plugin.json)
/bench       boards, metrics, runners; corpus/manifest.json = external board corpus
/docker      kicad-cli DRC/ERC runner image
/docs        details; read on demand, not by default
```

## Commands (fill in as they exist)
- Build: `cargo build`
- Test (quiet): `cargo test -q 2>&1 | tail -n 30`
- DRC one board: `kicad-cli pcb drc --format json --severity-error --refill-zones --exit-code-violations -o out/drc.json <board>`; exit code 5 = violations (only with `--exit-code-violations`). `--refill-zones` is KiCad 10+ only. Always parse the JSON; do not trust exit code alone.
- DRC in Docker (preferred): `docker build --build-arg KICAD_TAG=9.0 -f docker/Dockerfile -t kal-drc:9.0 .` then `docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp -v "$PWD:/work" kal-drc:9.0 <board> out`; writes `out/drc.json`, `out/summary.json`, `out/kicad_version.txt`; exit 0 clean, 1 violations, 2 failure.
- Summarize DRC JSON: `python3 orchestrator/drc_summary.py out/drc.json [--top 10] [--json] [--fail-on error|warning|never]`; exit 0 clean, 1 violations, 2 bad input.
- Compare two DRC JSONs: `python3 orchestrator/drc_compare.py a.json b.json`; exit 0 identical, 1 different, 2 bad input.
- Validate constraints: `python3 orchestrator/constraints.py <file> [--require-approved] [--json]`; exit 0 valid, 1 invalid, 2 unreadable.
- Rules from constraints: `python3 orchestrator/dru.py <constraints.json> -o <board>.kicad_dru` (approved only; KiCad loads `<project>.kicad_dru` next to `<project>.kicad_pro`); exit 0 ok, 1 invalid, 2 unreadable.
- Board summary: `cargo run -q --bin kal-summary -- <board.kicad_pcb>` prints JSON (`kal-board-summary/1`); exit 0 ok, 2 error.
- Round-trip one file: `cargo run -q --bin kal-roundtrip -- <in> <out> [--canonical]`; exit 0 ok, 1 mismatch, 2 error.
- Round-trip corpus: `bash bench/roundtrip.sh target/release/kal-roundtrip kal-drc:10.0 out/roundtrip <dirs>...` (relative paths); report in `out/roundtrip/report.tsv`.
- Fetch external corpus: `python3 bench/fetch_corpus.py bench/corpus/manifest.json corpus/external [--shard i/n] [--only ID ...]`; writes `lock.json` (resolved commits) and `fetch.tsv`.
- Test orchestrator / bench: `python3 -m unittest discover -s orchestrator/tests -q`, `python3 -m unittest discover -s bench/tests -q`
- CI: `.github/workflows/ci.yml` (rust fmt/clippy/test, python unittest, DRC smoke, generated-rules check, demo board summaries and round-trip on KiCad 9.0 + 10.0); `.github/workflows/corpus.yml` (external corpus, 2 KiCad versions x 4 shards; manual, weekly, PRs touching ir/bench/docker). Verify changes there, read failures with job logs (tail only).
- Bench: `TODO`

## KiCad facts (verify before relying)
- KiCad 10.0.x is current stable. IPC API on 9/10 needs a running GUI; headless IPC + export are KiCad 11 (release date unconfirmed).
- `(severity exclusion)` custom rules may appear without `excluded` key in DRC JSON (known bug).
- `kicad-cli sch erc` can exit 0 with violations: parse JSON.
- `kicad-cli pcb drc --refill-zones` does not exist in 9.x (verified 9.0.9: "Unknown argument"); 9.x checks zones as saved. Verified present in 10.0.6.
- Test matrix: KiCad 9, 10, 11-nightly when available. Round-trip (open/save/DRC) on 100 open boards must show zero diff.

## Conventions
- Small PRs, one concern each. Tests with every geometry/constraint change.
- Constraint schema example: `{"type":"max_distance","from":"C12","to":"U1.7","value_mm":2.0,"source":{"doc":"datasheet.pdf","page":14}}`
- Errors: typed results, no panics in engine on bad boards; return structured failure reason.
- Benchmark metrics: DRC errors, unconnected, completion %, wirelength, vias, area, rule violations (decoupling, diff pair skew), wall time, human cleanup minutes.
- Corpus boards are fetched, never committed. Their license is in the manifest; using a board for anything beyond testing (rules, constraints, shipped data) needs a license check first.

## Token-efficient workflow (for Claude)
- Grep/Glob first, then Read only the needed line ranges. Never read whole large files or whole boards.
- Do not re-read a file after Edit/Write succeeded.
- Never print raw DRC JSON, board files or long logs. Summarize with a script (counts by type, top 10 items) and show that.
- Run tests/builds with quiet flags; pipe through `tail -n 30` when output is long.
- Wide searches across many files -> use a subagent and keep only its conclusion.
- Plan briefly before multi-file changes; then implement in small steps; stop when the stated acceptance check passes.
- Keep answers short: what changed, result of the check, next step. No recaps of steps, no restating the task.
- Long design notes go in `/docs/*.md`; reference them by path, do not paste them into chat. Start a fresh session per task and carry state in docs and commit messages.
- Do not add dependencies, abstractions or features beyond the current phase.

## Current phase: 1 (rules + review)
Started by owner decision before phase 0's exit criterion was met. Phase 0 leftovers, run in parallel: grow the corpus to 100 boards, pin corpus commits, get the corpus workflow green.

Phase 1 goal: datasheet -> constraints -> `.kicad_dru`/netclasses; LLM design review on a JSON board summary. Target: extraction precision >= 90% on an internal labeled set.
Order: (1) constraint schema + validator, (2) approved constraints -> `.kicad_dru`, checked with kicad-cli (netclass definitions later), (3) board summary JSON from `kal_ir::sexpr`, (4) LLM extraction + review (needs an API key secret and a human-labeled set).

Later phases (do not start early):
2. Semi-auto placement: decoupling/sub-circuit (CP-SAT), block floorplan, one-click Freerouting trial.
3. End-to-end simple boards (2-4 layers, <=150 parts): own router, diff pairs, length tuning, parallel candidates, KiCad 11 headless IPC.
4. Mid complexity (4-6 layers, BGA fanout). High-speed DDR/RF/HDI stays assistant-only.

## Open questions (resolve, then delete from here)
- Final product name.
- Cloud vs on-prem first.
