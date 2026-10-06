import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import constraints  # noqa: E402
import extract_eval  # noqa: E402

EXAMPLE = Path(__file__).parent / "fixtures" / "constraints_example.json"


def doc(*items):
    return {"version": 1, "constraints": list(items)}


def lm(cid, nets, tol=0.1, page=3):
    src = {"doc": "g.pdf", "page": page}
    return {"id": cid, "type": "length_match", "nets": nets, "tolerance_mm": tol, "source": src}


def norm(d):
    cs, errors = constraints.validate(d)
    assert not errors, errors
    return cs


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = extract_eval.main([str(a) for a in argv])
    return code, out.getvalue()


class ScoreTest(unittest.TestCase):
    def test_example_matches_itself(self):
        labeled = norm(constraints.load_file(EXAMPLE))
        predicted = [dict(c, id=f"x{i}", approved=False) for i, c in enumerate(labeled)]
        s = extract_eval.score(predicted, labeled)
        self.assertEqual((s["precision"], s["recall"]), (1.0, 1.0))
        self.assertEqual(s["source_errors"], [])

    def test_value_mm_vs_nm_and_net_order(self):
        labeled = norm(doc(lm("a", ["D0", "D1"], tol=0.1)))
        predicted = norm(doc(lm("p", ["D1", "D0"], tol=0.100)))
        self.assertEqual(extract_eval.score(predicted, labeled)["matched"], 1)

    def test_wrong_value_missed_and_extra(self):
        labeled = norm(doc(lm("a", ["D0", "D1"]), lm("b", ["D2", "D3"])))
        predicted = norm(doc(lm("p", ["D0", "D1"], tol=0.2), lm("q", ["D2", "D3"])))
        s = extract_eval.score(predicted, labeled)
        self.assertEqual((s["matched"], s["precision"], s["recall"]), (1, 0.5, 0.5))
        self.assertEqual((s["false_positives"], s["missed"]), (["p"], ["a"]))

    def test_each_label_matches_once_and_page_is_checked(self):
        labeled = norm(doc(lm("a", ["D0", "D1"])))
        predicted = norm(doc(lm("p", ["D0", "D1"], page=4), lm("q", ["D0", "D1"])))
        s = extract_eval.score(predicted, labeled)
        self.assertEqual(s["matched"], 1)
        self.assertEqual(s["false_positives"], ["q"])
        self.assertEqual(s["source_errors"], ["p"])

    def test_empty_prediction(self):
        s = extract_eval.score([], norm(doc(lm("a", ["D0", "D1"]))))
        self.assertIsNone(s["precision"])
        self.assertEqual(s["recall"], 0.0)


class CliTest(unittest.TestCase):
    def test_threshold_and_bad_input(self):
        with tempfile.TemporaryDirectory() as d:
            lab, pred = Path(d) / "lab.json", Path(d) / "pred.json"
            lab.write_text(json.dumps(doc(lm("a", ["D0", "D1"]), lm("b", ["D2", "D3"]))))
            pred.write_text(json.dumps(doc(lm("p", ["D0", "D1"]), lm("q", ["D4", "D5"]))))
            code, out = run(pred, lab)
            self.assertEqual(code, 0)
            self.assertIn("precision 50.0% (1/2), recall 50.0% (1/2)", out)
            self.assertEqual(run(pred, lab, "--min-precision", "0.9")[0], 1)
            self.assertEqual(run(lab, lab, "--min-precision", "0.9")[0], 0)
            bad = Path(d) / "bad.json"
            bad.write_text('{"version": 1, "constraints": [{"id": "x"}]}')
            self.assertEqual(run(bad, lab)[0], 1)
            self.assertEqual(run(Path(d) / "missing.json", lab)[0], 2)


if __name__ == "__main__":
    unittest.main()
