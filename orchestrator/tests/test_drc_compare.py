import copy
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import drc_compare  # noqa: E402

SAMPLE = Path(__file__).parent / "fixtures" / "drc_sample.json"


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = drc_compare.main([str(a) for a in argv])
    return code, out.getvalue()


class CompareTest(unittest.TestCase):
    def setUp(self):
        self.report = json.loads(SAMPLE.read_text())
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def write(self, name, data):
        path = Path(self.tmp.name) / name
        path.write_text(json.dumps(data))
        return path

    def test_identical_ignores_metadata_and_order(self):
        other = copy.deepcopy(self.report)
        other["date"] = "another day"
        other["source"] = "elsewhere/copy.kicad_pcb"
        other["violations"].reverse()
        code, out = run(SAMPLE, self.write("b.json", other))
        self.assertEqual((code, out.strip()), (0, "identical"))

    def test_missing_violation_is_a_difference(self):
        other = copy.deepcopy(self.report)
        other["violations"].pop(0)
        code, out = run(SAMPLE, self.write("b.json", other))
        self.assertEqual(code, 1)
        self.assertIn("violations: 1 only in a, 0 only in b", out)
        self.assertIn("-1 [error] clearance", out)

    def test_moved_item_is_a_difference(self):
        other = copy.deepcopy(self.report)
        other["violations"][0]["items"][0]["pos"]["x"] = 6
        self.assertEqual(run(SAMPLE, self.write("b.json", other))[0], 1)

    def test_unconnected_items_compare_without_items(self):
        other = copy.deepcopy(self.report)
        item = other["unconnected_items"][0]["items"][0]
        item["description"], item["pos"]["x"] = "Pad 3 [NET1] of R2", 6
        code, out = run(SAMPLE, self.write("b.json", other))
        self.assertEqual((code, out.strip()), (0, "identical"))
        other["unconnected_items"].append(copy.deepcopy(other["unconnected_items"][0]))
        code, out = run(SAMPLE, self.write("c.json", other))
        self.assertEqual(code, 1)
        self.assertIn("unconnected_items: 0 only in a, 1 only in b", out)

    def test_silk_overlap_compares_without_items(self):
        other = copy.deepcopy(self.report)
        silk = next(v for v in other["violations"] if v["type"] == "silk_overlap")
        silk["items"] = [{"description": "Text on F.Silkscreen", "pos": {"x": 7, "y": 8}}]
        code, out = run(SAMPLE, self.write("b.json", other))
        self.assertEqual((code, out.strip()), (0, "identical"))
        silk["description"] = "Silkscreen clearance"
        self.assertEqual(run(SAMPLE, self.write("c.json", other))[0], 1)

    def test_item_order_is_ignored(self):
        other = copy.deepcopy(self.report)
        pair = [
            {"description": "Via [GND] on F.Cu - B.Cu", "pos": {"x": 1, "y": 2}},
            {"description": "Pad 1 [VCC] of C1", "pos": {"x": 3, "y": 4}},
        ]
        self.report["violations"][0]["items"] = pair
        other["violations"][0]["items"] = list(reversed(pair))
        code, out = run(self.write("a.json", self.report), self.write("b.json", other))
        self.assertEqual((code, out.strip()), (0, "identical"))

    def test_hole_clearance_compares_without_items(self):
        hole = {
            "type": "hole_clearance",
            "severity": "error",
            "description": "Hole clearance violation (actual 0.2290 mm)",
            "items": [{"description": "Via [GND]", "pos": {"x": 1, "y": 2}}],
        }
        other = copy.deepcopy(self.report)
        self.report["violations"].append(hole)
        moved = copy.deepcopy(hole)
        moved["items"] = [{"description": "Hole of J1", "pos": {"x": 5, "y": 6}}]
        other["violations"].append(moved)
        code, out = run(self.write("a.json", self.report), self.write("b.json", other))
        self.assertEqual((code, out.strip()), (0, "identical"))

    def test_bad_input_exit_2(self):
        self.assertEqual(run(SAMPLE, Path(self.tmp.name) / "missing.json")[0], 2)


if __name__ == "__main__":
    unittest.main()
