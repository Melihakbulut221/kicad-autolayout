import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "orchestrator"))

import constraints  # noqa: E402

EXTRACTION = ROOT / "bench" / "extraction"


def selector_nets(c):
    for key in ("a", "b", "on"):
        if key in c and "nets" in c[key]:
            yield from c[key]["nets"]
    yield from c.get("nets", [])
    for key in ("p", "n"):
        if key in c:
            yield c[key]


class LabeledSetTest(unittest.TestCase):
    def test_labeled_files_are_valid_and_cite_known_sources(self):
        listed = json.loads((EXTRACTION / "sources.json").read_text())["sources"]
        sources = {s["id"]: s for s in listed}
        files = sorted((EXTRACTION / "labeled").glob("*.json"))
        self.assertTrue(files)
        for path in files:
            with self.subTest(path.name):
                doc = constraints.load_file(path)
                cs, errors = constraints.validate(doc)
                self.assertEqual(errors, [])
                self.assertIn(path.stem, sources)
                src = sources[path.stem]
                self.assertEqual(doc["board"], src["board"])
                board = EXTRACTION / "boards" / f"{doc['board']}.json"
                nets = set(json.loads(board.read_text())["nets"])
                for c in cs:
                    self.assertEqual(c["source"]["doc"], path.stem, c["id"])
                    self.assertLessEqual(c["source"]["page"], src["pages"], c["id"])
                    self.assertEqual(set(selector_nets(c)) - nets, set(), c["id"])


if __name__ == "__main__":
    unittest.main()
