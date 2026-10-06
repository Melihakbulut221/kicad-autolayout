import copy
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import constraints  # noqa: E402

EXAMPLE = Path(__file__).parent / "fixtures" / "constraints_example.json"


def doc_with(**fields):
    """A one-constraint document; a field set to None is removed."""
    base = {
        "id": "x",
        "type": "clearance",
        "a": {"netclass": "HV"},
        "min_mm": 0.5,
        "source": {"doc": "d.pdf", "page": 1},
    }
    base.update(fields)
    return {"version": 1, "constraints": [{k: v for k, v in base.items() if v is not None}]}


def errors_of(doc):
    return constraints.validate(doc)[1]


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = constraints.main([str(a) for a in argv])
    return code, out.getvalue(), err.getvalue()


class ValidateTest(unittest.TestCase):
    def test_example_is_valid_and_normalized(self):
        cs, errors = constraints.validate(constraints.load_file(EXAMPLE))
        self.assertEqual(errors, [])
        self.assertEqual(len(cs), 7)
        by_id = {c["id"]: c for c in cs}
        self.assertEqual(by_id["ddr-clk-dp"]["width_nm"], 100_000)
        self.assertEqual(by_id["ddr-clk-dp"]["max_uncoupled_nm"], 2_000_000)
        self.assertEqual(by_id["ddr-dq0-match"]["tolerance_nm"], 127_000)
        self.assertEqual(by_id["c12-near-u1"]["max_nm"], 2_000_000)
        self.assertEqual(by_id["pwr-width"], {**by_id["pwr-width"], "min_nm": 300_000})
        self.assertNotIn("max_nm", by_id["pwr-width"])
        self.assertFalse(by_id["usb-imp"]["approved"])
        self.assertEqual(len(constraints.approved_only(cs)), 4)

    def test_minimal_valid(self):
        self.assertEqual(errors_of(doc_with()), [])

    def test_rejections(self):
        cases = {
            "no source": doc_with(source=None),
            "no page": doc_with(source={"doc": "d.pdf"}),
            "approved without reviewer": doc_with(approved=True),
            "unknown field": doc_with(min_mn=0.5),
            "unknown type": doc_with(type="warp"),
            "zero clearance": doc_with(min_mm=0),
            "bool number": doc_with(min_mm=True),
            "finer than 1 nm": doc_with(min_mm=Decimal("0.0000001")),
            "two selector keys": doc_with(a={"nets": ["A"], "netclass": "HV"}),
            "empty nets": doc_with(a={"nets": []}),
            "bad id": doc_with(id="has space"),
            "diff pair same net": doc_with(
                type="diff_pair", a=None, min_mm=None, p="X", n="X", width_mm=0.1, gap_mm=0.1
            ),
            "length match one net": doc_with(
                type="length_match", a=None, min_mm=None, nets=["A"], tolerance_mm=0.1
            ),
            "width order": doc_with(
                type="track_width", a=None, on={"netclass": "P"}, min_mm=0.5, max_mm=0.2
            ),
            "bad ref": doc_with(
                type="max_distance", a=None, min_mm=None, value_mm=1, **{"from": "12C", "to": "U1"}
            ),
            "impedance kind": doc_with(
                type="impedance", a=None, min_mm=None, on={"netclass": "U"}, ohms=90, kind="diff"
            ),
        }
        for name, doc in cases.items():
            with self.subTest(name):
                self.assertEqual(len(errors_of(doc)), 1, errors_of(doc))

    def test_duplicate_ids_and_bad_documents(self):
        doc = doc_with()
        doc["constraints"].append(copy.deepcopy(doc["constraints"][0]))
        self.assertEqual(errors_of(doc), ["constraints[1] (x): duplicate id"])
        self.assertTrue(errors_of({"constraints": []}))
        self.assertTrue(errors_of({"version": 1, "constraints": {}}))


class CliTest(unittest.TestCase):
    def test_summary(self):
        code, out, _ = run(EXAMPLE)
        self.assertEqual(code, 0)
        self.assertIn("7 valid (4 approved), 0 error(s)", out)

    def test_require_approved(self):
        code, _, err = run(EXAMPLE, "--require-approved")
        self.assertEqual(code, 1)
        self.assertIn("usb-imp: not approved", err)

    def test_json_output(self):
        code, out, _ = run(EXAMPLE, "--json")
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual([c["id"] for c in data["constraints"]][:2], ["ddr-clk-dp", "ddr-dq0-match"])

    def test_unreadable(self):
        with tempfile.TemporaryDirectory() as d:
            bad = Path(d) / "bad.json"
            bad.write_text("{nope")
            self.assertEqual(run(bad)[0], 2)
            self.assertEqual(run(Path(d) / "missing.json")[0], 2)


if __name__ == "__main__":
    unittest.main()
