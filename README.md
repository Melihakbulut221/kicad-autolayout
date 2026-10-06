# kicad-autolayout (working name)

Automatic PCB placement and routing for KiCad. An LLM orchestrates; geometry and optimization engines do the layout; KiCad's own DRC is the judge.

| Dir | What |
|---|---|
| `core/` | Rust engine: geometry, placement, routing (`kal-core`) |
| `ir/` | Board IR, integer nanometers (`kal-ir`) |
| `orchestrator/` | LLM layer + DRC loop (Python) |
| `plugin/` | Thin KiCad IPC plugin (open source) |
| `bench/` | Benchmark boards and runners |
| `docs/` | Design notes |

```sh
cargo build
cargo test -q
```

See `CLAUDE.md` for rules and the phase plan.
