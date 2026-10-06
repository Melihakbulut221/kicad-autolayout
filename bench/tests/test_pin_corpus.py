import io
import json
import sys
import urllib.error
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pin_corpus  # noqa: E402

MANIFEST = Path(__file__).resolve().parents[1] / "corpus" / "manifest.json"
SHA_A = "a" * 40
SHA_B = "b" * 40


def board(bid, **extra):
    b = {"id": bid, "repo": f"o/{bid}", "ref": "main"}
    b.update(extra)
    b.update({"pcb": [f"{bid}.kicad_pcb"], "license": "MIT", "interfaces": ["pcie"]})
    return b


def not_found(*_):
    raise urllib.error.HTTPError("u", 404, "Not Found", None, io.BytesIO())


class PinTest(unittest.TestCase):
    def test_repo_manifest_keeps_its_layout(self):
        text = MANIFEST.read_text(encoding="utf-8")
        self.assertEqual(pin_corpus.format_manifest(json.loads(text)), text)

    def test_commit_goes_after_ref(self):
        data = {"note": "n", "boards": [board("x", commit=SHA_A)]}
        line = pin_corpus.format_manifest(data).splitlines()[3]
        self.assertLess(line.index('"ref"'), line.index('"commit"'))
        self.assertLess(line.index('"commit"'), line.index('"pcb"'))

    def test_pins_unpinned_and_keeps_pinned(self):
        data = {"boards": [board("new"), board("old", commit=SHA_B)]}
        rows, failures = pin_corpus.pin(data, False, None, lambda r, f: SHA_A, lambda *a: None)
        self.assertEqual(failures, 0)
        self.assertEqual(rows, [("new", "pinned", SHA_A), ("old", "same", SHA_B)])
        self.assertEqual([b["commit"] for b in data["boards"]], [SHA_A, SHA_B])

    def test_refresh_and_only(self):
        data = {"boards": [board("a", commit=SHA_B), board("b", commit=SHA_B)]}
        rows, _ = pin_corpus.pin(data, True, ["a"], lambda r, f: SHA_A, lambda *a: None)
        self.assertEqual(rows, [("a", "pinned", SHA_A)])
        self.assertEqual([b["commit"] for b in data["boards"]], [SHA_A, SHA_B])

    def test_missing_path_fails_and_leaves_board(self):
        data = {"boards": [board("x")]}
        rows, failures = pin_corpus.pin(data, False, None, lambda r, f: SHA_A, not_found)
        self.assertEqual(failures, 1)
        self.assertEqual(rows, [("x", "error", "missing path or ref")])
        self.assertNotIn("commit", data["boards"][0])


if __name__ == "__main__":
    unittest.main()
