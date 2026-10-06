"""Canvas layout of the n8n workflow: sticky notes fit their text and stay clear of the nodes below them."""
import json
import math
import re
import unittest
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[2] / "n8n" / "draftstudio_pipeline.workflow.json"
GAP = 40  # canvas units between a note's bottom edge and the highest node below it


def _nodes():
    return json.loads(WORKFLOW.read_text())["nodes"]


def needed_height(content, width):
    """Estimated height n8n needs to show a markdown sticky note without clipping.

    Calibrated on a canvas screenshot of the three notes at 380 high (2026-10-05): the Overview and
    Credentials notes fit, the Models note was clipped two lines short; this estimate gives 350, 358 and 386.
    """
    chars_per_line = int((width - 40) / 6.4)
    total = 32  # padding
    for line in content.split("\n"):
        text = re.sub(r"[*`#]", "", line).strip()
        if line.startswith("#"):
            total += 34
        elif not text:
            total += 12
        else:
            total += math.ceil(len(text) / chars_per_line) * 20
    return total


class StickyNoteTests(unittest.TestCase):
    def setUp(self):
        nodes = _nodes()
        self.notes = [n for n in nodes if n["type"] == "n8n-nodes-base.stickyNote"]
        self.others = [n for n in nodes if n["type"] != "n8n-nodes-base.stickyNote"]

    def test_there_are_three_notes(self):
        self.assertEqual(len(self.notes), 3)

    def test_every_note_is_tall_enough_for_its_text(self):
        for note in self.notes:
            p = note["parameters"]
            with self.subTest(note=note["name"]):
                self.assertGreaterEqual(p["height"], needed_height(p["content"], p["width"]))

    def test_notes_stay_clear_of_the_nodes_below_them(self):
        for note in self.notes:
            left = note["position"][0]
            right = left + note["parameters"]["width"]
            # a node counts when it starts under the note (a wide agent node reaches about 240 units left of its position)
            below = [n for n in self.others if left - 240 < n["position"][0] < right and n["position"][1] > note["position"][1]]
            with self.subTest(note=note["name"]):
                self.assertTrue(below)
                bottom = note["position"][1] + note["parameters"]["height"]
                self.assertLessEqual(bottom + GAP, min(n["position"][1] for n in below))

    def test_notes_do_not_overlap_each_other(self):
        spans = sorted((n["position"][0], n["position"][0] + n["parameters"]["width"], n["name"]) for n in self.notes)
        for (_, right, a), (left, _, b) in zip(spans, spans[1:]):
            with self.subTest(pair=(a, b)):
                self.assertLessEqual(right, left)


if __name__ == "__main__":
    unittest.main()
