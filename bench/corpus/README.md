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

## Run
```sh
python3 bench/fetch_corpus.py bench/corpus/manifest.json corpus/external [--shard 0/4] [--only ID ...]
bash bench/roundtrip.sh target/release/kal-roundtrip kal-drc:10.0 out/roundtrip corpus/external
```
CI: `.github/workflows/corpus.yml` (manual, weekly, and on PRs touching ir/bench/docker).
`corpus/external/lock.json` records the resolved commit of every board; copy those into
`commit` fields to pin.

## Interface coverage (37 boards)
| interface | boards | good first target |
|---|---|---|
| DDR3 / DDR3L | kintex-410t, butterstick, orangecrab, a64-olinuxino, zynqpcb | orangecrab (DDR3 x16) |
| DDR4 | rdimm-ddr4-tester | |
| DDR5 | sodimm-ddr5-tester, rdimm-ddr5-tester, ddr5-testbed | ddr5-testbed (6 layers) |
| LPDDR4 / LPDDR5 | lpddr4-test-board, lpddr4-testbed, imx8mp-som, lpddr5-testbed | lpddr4-testbed (6 layers) |
| PCIe / Thunderbolt | m2-pcie, m2-oculink, oculink-pcie, 3x thunderbolt, com-express-7, cm4, jetson-orin, openpcie backplane, picoevb, ... | m2-pcie-adapter (4 layers, passive) |
| USB 3.x / USB-C | jetson-orin, kria-k26, com-express-7, jetson-agx-thor | |
| 10G Ethernet / SFP | com-express-7, jetson-agx-thor, thunderbolt-10gbe | |
| Gigabit Ethernet | most baseboards | |
| MIPI CSI / DSI, LVDS, GMSL | ov5640-dual-camera, gmsl-serializer, cm4-lvds-adapter, jetson/kria/cm4 baseboards | ov5640-dual-camera |
| HDMI / DisplayPort | hdmi-edid-debug, many baseboards | hdmi-edid-debug |
| FPGA SerDes | kintex-410t (FMC+), butterstick (SYZYGY), picoevb (GTP), thor (FMC+) | |
| SI test structures | signal-integrity-test-board | |

Gaps: no JESD204, no explicit SGMII, no DDR4 SO-DIMM, no standalone USB3 device board.
KiCad 4/5-format boards (orangecrab, picoevb, Olimex, zynqpcb) also test legacy-format loading.
Unverified or rejected candidates are listed in the PR that added this file.
