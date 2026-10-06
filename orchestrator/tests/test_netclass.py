import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import constraints  # noqa: E402
import netclass  # noqa: E402

RULES = Path(__file__).resolve().parents[2] / "bench" / "boards" / "rules"
SRC = {"doc": "d.pdf", "page": 1}


def nc(**kw):
    c = {"id": "n", "type": "netclass", "name": "HV", "patterns": ["HV*"], "clearance_mm": 0.5}
    c.update(source=SRC, approved=True, approved_by="me", **kw)
    return c


def normalized(*items):
    cs, errors = constraints.validate({"version": 1, "constraints": list(items)})
    assert not errors, errors
    return cs


def run(*argv):
    err = io.StringIO()
    with redirect_stderr(err):
        code = netclass.main([str(a) for a in argv])
    return code, err.getvalue()


class ValidateTest(unittest.TestCase):
    def test_normalizes_sizes(self):
        (c,) = normalized(nc(track_width_mm=0.127, via_diameter_mm=0.6, via_drill_mm=0.3))
        self.assertEqual(c["clearance_nm"], 500_000)
        self.assertEqual(c["track_width_nm"], 127_000)
        self.assertEqual(c["patterns"], ["HV*"])

    def test_rejects_bad_netclasses(self):
        cases = {
            "default": nc(name="Default"),
            "no sizes": nc(clearance_mm=None),
            "no patterns": nc(patterns=[]),
            "drill too big": nc(via_diameter_mm=0.3, via_drill_mm=0.3),
            "unknown field": nc(min_mm=1),
        }
        for name, c in cases.items():
            c = {k: v for k, v in c.items() if v is not None}
            with self.subTest(name):
                _, errors = constraints.validate({"version": 1, "constraints": [c]})
                self.assertEqual(len(errors), 1, errors)


class ApplyTest(unittest.TestCase):
    def test_new_net_settings(self):
        project = {"meta": {"filename": "b.kicad_pro", "version": 1}}
        names = netclass.apply(project, normalized(nc(track_width_mm=0.3)))
        self.assertEqual(names, ["HV"])
        net = project["net_settings"]
        default, hv = net["classes"]
        self.assertEqual(default["name"], "Default")
        self.assertEqual((hv["clearance"], hv["track_width"]), (0.5, 0.3))
        self.assertEqual(hv["via_diameter"], default["via_diameter"])
        self.assertNotIn("priority", hv)
        self.assertEqual(net["netclass_patterns"], [{"netclass": "HV", "pattern": "HV*"}])

    def test_replaces_same_name_and_keeps_others(self):
        project = {
            "net_settings": {
                "classes": [
                    {"name": "Default", "clearance": 0.2, "priority": 2147483647},
                    {"name": "HV", "clearance": 1, "priority": 0},
                    {"name": "PWR", "clearance": 0.3, "priority": 1},
                ],
                "netclass_patterns": [
                    {"netclass": "HV", "pattern": "OLD*"},
                    {"netclass": "PWR", "pattern": "+5V"},
                ],
            }
        }
        netclass.apply(project, normalized(nc(clearance_mm=2)))
        classes = {k["name"]: k for k in project["net_settings"]["classes"]}
        self.assertEqual(classes["HV"]["clearance"], 2)
        self.assertEqual(classes["PWR"]["clearance"], 0.3)
        self.assertEqual(classes["Default"]["priority"], 2147483647)
        others = sorted(k["priority"] for n, k in classes.items() if n != "Default")
        self.assertEqual(others, [0, 1])
        self.assertEqual(
            project["net_settings"]["netclass_patterns"],
            [{"netclass": "PWR", "pattern": "+5V"}, {"netclass": "HV", "pattern": "HV*"}],
        )

    def test_duplicate_class_is_a_conflict(self):
        cs = normalized(nc(), nc(id="m"))
        with self.assertRaises(netclass.Conflict):
            netclass.apply({}, cs)

    def test_mm_is_exact(self):
        self.assertEqual(netclass.mm(127_000), 0.127)
        self.assertEqual(netclass.mm(2_000_000), 2)
        self.assertIsInstance(netclass.mm(2_000_000), int)


class CliTest(unittest.TestCase):
    def test_rules_board(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "rules.kicad_pro"
            code, err = run(RULES / "netclass.json", RULES / "rules.kicad_pro", "-o", out)
            self.assertEqual(code, 0, err)
            self.assertIn("1 class(es)", err)
            net = json.loads(out.read_text())["net_settings"]
        # The unapproved DDR_DQ class never reaches the project (rule 6).
        self.assertEqual([k["name"] for k in net["classes"]], ["Default", "HV"])

    def test_invalid_and_unreadable(self):
        with tempfile.TemporaryDirectory() as d:
            bad = Path(d) / "bad.json"
            bad.write_text('{"version": 1, "constraints": [{"id": "x"}]}')
            pro = Path(d) / "b.kicad_pro"
            pro.write_text("{}")
            self.assertEqual(run(bad, pro)[0], 1)
            self.assertEqual(run(Path(d) / "missing.json", pro)[0], 2)
            self.assertEqual(run(RULES / "netclass.json", Path(d) / "missing.kicad_pro")[0], 2)


if __name__ == "__main__":
    unittest.main()
