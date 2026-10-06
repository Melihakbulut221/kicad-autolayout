import io
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import constraints  # noqa: E402
import dru  # noqa: E402

EXAMPLE = Path(__file__).parent / "fixtures" / "constraints_example.json"
RULES_BOARD = Path(__file__).resolve().parents[2] / "bench" / "boards" / "rules" / "constraints.json"


def approved(path=EXAMPLE):
    cs, errors = constraints.validate(constraints.load_file(path))
    assert not errors, errors
    return constraints.approved_only(cs)


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = dru.main([str(a) for a in argv])
    return code, out.getvalue(), err.getvalue()


class RenderTest(unittest.TestCase):
    def test_mm_is_exact(self):
        self.assertEqual(dru.mm(127_000), "0.127mm")
        self.assertEqual(dru.mm(2_000_000), "2mm")
        self.assertEqual(dru.mm(10_000_000), "10mm")
        self.assertEqual(dru.mm(0), "0mm")
        self.assertEqual(dru.mm(1), "0.000001mm")

    def test_example_rules(self):
        text, skipped = dru.render(approved())
        self.assertEqual(skipped, [])
        self.assertTrue(text.startswith("(version 1)\n"))
        self.assertRegex(text, r"# ruleset sha256 [0-9a-f]{64}\n")
        self.assertIn(
            '(rule "kal:hv-clear"\n'
            "\t(condition \"A.NetClass == 'HV'\")\n"
            "\t(constraint clearance (min 0.5mm)))\n",
            text,
        )
        self.assertIn("(constraint track_width (min 0.3mm) (opt 0.5mm)))", text)
        self.assertIn("A.NetName == 'DDR_DQ0' || A.NetName == 'DDR_DQ1'", text)
        self.assertIn("(constraint skew (max 0.127mm)))", text)
        self.assertIn("(constraint diff_pair_uncoupled (max 2mm))", text)
        self.assertIn("(constraint skew (max 0.05mm)))", text)
        # Unapproved constraints never reach the rules (rule 6).
        self.assertNotIn("usb-imp", text)
        self.assertNotIn("c12-near-u1", text)

    def test_parens_balance_outside_comments(self):
        text, _ = dru.render(approved(RULES_BOARD))
        body = "\n".join(line for line in text.splitlines() if not line.startswith("#"))
        self.assertEqual(body.count("("), body.count(")"))
        self.assertEqual(len(re.findall(r'^\(rule "', body, re.M)), 5)

    def test_not_expressible_and_bad_names_are_listed(self):
        cs = approved(RULES_BOARD)
        bad = dict(cs[0], id="quoted", a={"nets": ["it's"]})
        text, skipped = dru.render(cs + [bad])
        self.assertEqual(len(skipped), 2)
        self.assertTrue(skipped[0].startswith("c1-near-u1 (max_distance)"))
        self.assertTrue(skipped[1].startswith("quoted (clearance)"))
        self.assertIn("# not emitted: c1-near-u1", text)

    def test_length_window_from_target(self):
        text, _ = dru.render(approved(RULES_BOARD))
        self.assertIn("(constraint length (min 19.9mm) (max 20.1mm))", text)

    def test_hash_tracks_content(self):
        cs = approved()
        changed = [dict(cs[0], width_nm=cs[0]["width_nm"] + 1)] + cs[1:]
        self.assertEqual(dru.ruleset_hash(cs), dru.ruleset_hash(approved()))
        self.assertNotEqual(dru.ruleset_hash(cs), dru.ruleset_hash(changed))


class CliTest(unittest.TestCase):
    def test_writes_file(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "b.kicad_dru"
            code, _, err = run(EXAMPLE, "-o", out)
            self.assertEqual(code, 0)
            self.assertIn("dru: 4 rule(s); 3 unapproved skipped", err)
            self.assertTrue(out.read_text().startswith("(version 1)"))

    def test_invalid_and_unreadable(self):
        with tempfile.TemporaryDirectory() as d:
            bad = Path(d) / "bad.json"
            bad.write_text('{"version": 1, "constraints": [{"id": "x"}]}')
            self.assertEqual(run(bad)[0], 1)
            self.assertEqual(run(Path(d) / "missing.json")[0], 2)


if __name__ == "__main__":
    unittest.main()
