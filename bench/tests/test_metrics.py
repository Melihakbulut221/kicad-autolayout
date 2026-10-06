import json
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import metrics  # noqa: E402

SUMMARY = {
    "schema": "kal-board-summary/1",
    "copper_layers": ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"],
    "outline_nm": ["1000000", "2000000", "51000000", "32000000"],
    "counts": {"nets": 4, "footprints": 3, "pads": 9, "segments": 12, "arcs": 1, "vias": 2,
               "zones": 1},
    "nets": ["", "GND", "VCC", "SIG"],
    "segment_length_nm": {"GND": "1500000", "VCC": "2500000", "SIG": "0"},
}  # fmt: skip
DRC = {
    "kicad_version": "10.0.6",
    "active_by_severity": {"error": 3, "warning": 5},
    "sections": {"unconnected_items": {"total": 4, "excluded": 1}},
}


class RowTest(unittest.TestCase):
    def test_row_from_summary_and_drc(self):
        r = metrics.row("b", SUMMARY, DRC)
        self.assertEqual(list(r), list(metrics.COLUMNS))
        self.assertEqual(r["layers"], 4)
        self.assertEqual((r["nets"], r["routed_nets"]), (3, 2))
        self.assertEqual(r["track_length_nm"], 4_000_000)
        self.assertEqual((r["board_w_nm"], r["board_h_nm"]), (50_000_000, 30_000_000))
        self.assertEqual((r["drc_errors"], r["drc_warnings"], r["unconnected"]), (3, 5, 3))
        self.assertEqual(r["kicad"], "10.0.6")

    def test_missing_drc_and_outline(self):
        summary = {**SUMMARY, "outline_nm": None}
        r = metrics.row("b", summary, None)
        self.assertIsNone(r["board_w_nm"])
        self.assertIsNone(r["drc_errors"])
        self.assertEqual(metrics.tsv([r]).splitlines()[1].split("\t")[-1], "")


class CollectTest(unittest.TestCase):
    def test_collect_pairs_board_and_drc(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            fake = tmp / "kal-summary"
            fake.write_text(f"#!{sys.executable}\nimport sys\nprint({json.dumps(json.dumps(SUMMARY))})\n")
            fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
            out = tmp / "out"
            d = out / "corpus_external_brd_x"
            (d / "drc-orig").mkdir(parents=True)
            (d / "board.path").write_text("corpus/external/brd/x.kicad_pcb\n")
            (d / "drc-orig" / "summary.json").write_text(json.dumps(DRC))
            (out / "report.tsv").write_text("board\n")
            rows, failed = metrics.collect(fake, out)
        self.assertEqual(failed, [])
        self.assertEqual([r["id"] for r in rows], ["brd"])
        self.assertEqual(rows[0]["unconnected"], 3)
        self.assertIn("| brd | 4 | 3 | 3 | 2 | 4000000 | 3 | 3 |", metrics.markdown(rows))


if __name__ == "__main__":
    unittest.main()
