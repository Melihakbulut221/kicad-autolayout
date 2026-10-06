# External board corpus

`manifest.json` lists open-hardware KiCad boards with high-speed interfaces. They are the
regression set for S-expression round-trip and DRC, and the reference set the layout engine
is measured against in later phases (DDR, PCIe, USB3, ...). They are **not** training data:
the engine is algorithmic and the LLM never outputs geometry (CLAUDE.md hard rule 1).

## License policy
- Boards are fetched at CI time (`bench/fetch_corpus.py`) and never committed or embedded.
- `license` is what the repo states (checked on the repo page, not full legal review).
- Testing (round-trip, DRC, metrics) is fine for every entry.
- Using a board as a source for rules, constraints or anything shipped needs a full license
  check first; GPL / CC-BY-SA / CERN-OHL-S entries are test-only until reviewed.
- `unknown` (11 boards, no LICENSE file) and CC-BY-NC (1 board) are test-only, full stop.

## Run
```sh
python3 bench/fetch_corpus.py bench/corpus/manifest.json corpus/external [--shard 0/4] [--only ID ...]
bash bench/roundtrip.sh target/release/kal-roundtrip kal-drc:10.0 out/roundtrip corpus/external
```
CI: `.github/workflows/corpus.yml` (manual, weekly, and on PRs touching ir/bench/docker).
`corpus/external/lock.json` records the resolved commit of every board.

## Pin
Every board carries a `commit` (enforced by `bench/tests`), so corpus results compare like
with like. `python3 bench/pin_corpus.py bench/corpus/manifest.json [--refresh] [--only ID ...]`
resolves unpinned boards (all with `--refresh`), checks their `.kicad_pcb` paths exist at
that commit, and rewrites the manifest. In CI: run the **Corpus pin** workflow
(`corpus-pin.yml`); on main it pushes a `corpus-pin/<run id>` branch to open a PR from, on
another branch it commits there. New boards go in unpinned and get pinned by that workflow
before the PR merges.

## Interface coverage (106 boards)
| interface | boards | examples / good first target |
|---|---|---|
| DDR3 / DDR3L | 25 | orangecrab (DDR3 x16, first target), trellisboard, marble, h616-ddr3, zynq SoMs and SDRs, numato-opsis, dc-scm |
| DDR4 | 1 | rdimm-ddr4-tester |
| DDR5 | 3 | ddr5-testbed (6 layers, first target), sodimm/rdimm testers |
| LPDDR4 / LPDDR5 | 7 / 1 | lpddr4-testbed (first target), polarfire-som, arvsom, osm-l-bmc-som, h616-lpddr4, lpddr5-testbed |
| PCIe / Thunderbolt | 36 / 3 | m2-pcie-adapter (4 layers, passive, first target), trellisboard, kintex-pcie, job-pcie-switch, 3x thunderbolt |
| USB 3.x / USB-C | 10 / 20 | jetson-orin, kria-k26, system76-launch, syzygy-txr4-usb3 |
| 10G Ethernet / SFP | 4 | com-express-7, jetson-agx-thor, thunderbolt-10gbe, oculink-10gbe |
| Gigabit Ethernet | 36 | most baseboards and SoMs |
| MIPI CSI / DSI, LVDS, GMSL | 25 / 8 / 6 / 2 | ov5640-dual-camera, hdmi/sdi/cvbs-mipi bridges, gmsl adapters |
| HDMI / DisplayPort | 32 / 7 | hdmi-edid-debug (first target), numato-opsis, glider |
| FPGA SerDes / SATA / SDI | 18 | kintex-410t, butterstick, picoevb, fmc-sata, granit, sdi adapters |
| RF | 9 | hackrf-one, hermes-lite2, zynq + AD936x SDRs |
| SI test structures | 1 | signal-integrity-test-board |

KiCad formats: 5 (21 boards incl. one KiCad 4), 6 (18), 7 (17), 8 (8), 9 (33), 10 (5),
unknown (2, incl. the 2013-era Numato Opsis file). Legacy formats also test loading; a board
KiCad 9 cannot open (e.g. KiCad 10 format) is reported as `orig-error`, not a failure.

Gaps: no JESD204, one DDR4 board, one LPDDR5 board, few 10GbE boards. Open KiCad boards with
these are rare outside Antmicro; candidates welcome (verify the `.kicad_pcb` path and
license, add unpinned, run Corpus pin).
