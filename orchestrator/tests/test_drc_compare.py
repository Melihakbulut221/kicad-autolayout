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
        other["unconnected_items"][0]["items"][0]["pos"]["x"] = 6
        self.assertEqual(run(SAMPLE, self.write("b.json", other))[0], 1)

    def test_bad_input_exit_2(self):
        self.assertEqual(run(SAMPLE, Path(self.tmp.name) / "missing.json")[0], 2)


if __name__ == "__main__":
    unittest.main()
