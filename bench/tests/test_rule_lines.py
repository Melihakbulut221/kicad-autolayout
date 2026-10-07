import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "extraction"))

import rule_lines  # noqa: E402

TEXT = (
    "Title page\n"
    "\f"
    "Route DP/DM with 90 Ω differential impedance.\n"
    "Revision 1.2 released\n"
    "\f"
    "Keep intra-pair skew below 5 mils.\n"
    "Maximum trace length is 12 inches.\n"
    "Copyright 2016 Texas Instruments\n"
)


class RuleLinesTest(unittest.TestCase):
    def test_pages_and_filtering(self):
        self.assertEqual(
            rule_lines.rule_lines(TEXT),
            [
                "p2: Route DP/DM with 90 Ω differential impedance.",
                "p3: Keep intra-pair skew below 5 mils.",
                "p3: Maximum trace length is 12 inches.",
            ],
        )

    def test_limit(self):
        self.assertEqual(len(rule_lines.rule_lines(TEXT, limit=1)), 1)


if __name__ == "__main__":
    unittest.main()
