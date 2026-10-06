import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import drc_summary  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE = FIXTURES / "drc_sample.json"
CLEAN = FIXTURES / "drc_clean.json"


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = drc_summary.main([str(a) for a in argv])
    return code, out.getvalue(), err.getvalue()


class SummarizeTest(unittest.TestCase):
    def setUp(self):
        self.summary = drc_summary.summarize(drc_summary.load_report(SAMPLE))

    def test_counts_by_type_and_severity(self):
        v = self.summary["sections"]["violations"]
        self.assertEqual(v["total"], 5)
        self.assertEqual(v["by_type"], {"clearance": 2, "silk_overlap": 1})
        self.assertEqual(v["by_severity"], {"error": 2, "warning": 1})

    def test_exclusions_include_missing_excluded_key(self):
        self.assertEqual(self.summary["sections"]["violations"]["excluded"], 2)

    def test_unconnected_counted(self):
        self.assertEqual(self.summary["sections"]["unconnected_items"]["by_type"], {"unconnected_items": 1})
        self.assertEqual(self.summary["active_by_severity"], {"error": 3, "warning": 1})

    def test_top_is_capped_and_errors_first(self):
        top = drc_summary.summarize(drc_summary.load_report(SAMPLE), top=1)["sections"]["violations"]["top"]
        self.assertEqual(len(top), 1)
        self.assertEqual(top[0]["severity"], "error")
        self.assertEqual(top[0]["pos"], "(10.5, 20.25)")


class CliTest(unittest.TestCase):
    def test_violations_exit_1(self):
        code, out, _ = run(SAMPLE)
        self.assertEqual(code, 1)
        self.assertIn("violations: 5 (error 2, warning 1; excluded 2)", out)
        self.assertIn("    2  clearance", out)

    def test_clean_exit_0(self):
        code, out, _ = run(CLEAN)
        self.assertEqual(code, 0)
        self.assertIn("violations: 0", out)

    def test_fail_on_never(self):
        self.assertEqual(run(SAMPLE, "--fail-on", "never")[0], 0)

    def test_json_output(self):
        code, out, _ = run(SAMPLE, "--json", "--top", "0")
        data = json.loads(out)
        self.assertEqual(code, 1)
        self.assertEqual(data["kicad_version"], "10.0.1")
        self.assertEqual(data["sections"]["violations"]["top"], [])

    def test_bad_input_exit_2(self):
        with tempfile.TemporaryDirectory() as d:
            bad = Path(d) / "bad.json"
            bad.write_text("{not json")
            self.assertEqual(run(bad)[0], 2)
            other = Path(d) / "other.json"
            other.write_text('{"foo": 1}')
            self.assertEqual(run(other)[0], 2)
            self.assertEqual(run(Path(d) / "missing.json")[0], 2)


if __name__ == "__main__":
    unittest.main()
