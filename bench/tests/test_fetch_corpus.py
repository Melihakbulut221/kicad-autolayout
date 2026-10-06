import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fetch_corpus  # noqa: E402

MANIFEST = Path(__file__).resolve().parents[1] / "corpus" / "manifest.json"
BASE = {
    "id": "a",
    "repo": "o/r",
    "ref": "main",
    "pcb": ["x.kicad_pcb"],
    "license": "MIT",
    "interfaces": ["pcie"],
}


class ManifestTest(unittest.TestCase):
    def test_repo_manifest_is_valid(self):
        boards = fetch_corpus.load_manifest(MANIFEST)
        self.assertGreaterEqual(len(boards), 30)
        tags = {t for b in boards for t in b["interfaces"]}
        for needed in ("ddr4", "ddr5", "lpddr4", "pcie", "usb3", "10gbe", "mipi-csi"):
            self.assertIn(needed, tags)

    def test_shards_partition_boards(self):
        boards = fetch_corpus.load_manifest(MANIFEST)
        ids = [b["id"] for i in range(4) for b in fetch_corpus.select(boards, i, 4, None)]
        self.assertCountEqual(ids, [b["id"] for b in boards])
        only = fetch_corpus.select(boards, 0, 1, ["antmicro-m2-pcie-adapter"])
        self.assertEqual([b["id"] for b in only], ["antmicro-m2-pcie-adapter"])

    def test_rejects_bad_manifests(self):
        cases = {
            "empty": {"boards": []},
            "missing key": {"boards": [{"id": "a"}]},
            "duplicate": {"boards": [BASE, BASE]},
            "bad pcb": {"boards": [{**BASE, "pcb": ["x.sch"]}]},
            "unknown interface": {"boards": [{**BASE, "interfaces": ["warp-drive"]}]},
        }
        with tempfile.TemporaryDirectory() as d:
            for name, data in cases.items():
                path = Path(d) / "m.json"
                path.write_text(json.dumps(data))
                with self.subTest(name), self.assertRaises(fetch_corpus.ManifestError):
                    fetch_corpus.load_manifest(path)

    def test_parse_shard(self):
        self.assertEqual(fetch_corpus.parse_shard("1/4"), (1, 4))
        for bad in ("4/4", "x", "1/0", "-1/2"):
            with self.subTest(bad), self.assertRaises(fetch_corpus.ManifestError):
                fetch_corpus.parse_shard(bad)


if __name__ == "__main__":
    unittest.main()
