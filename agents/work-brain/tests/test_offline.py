"""Tests for reading raw notes and for the rule-based brain builder.

Most of these run against the real ``sample-notes`` folder, because the sample
notes are the answer key: they were written to contain a reversed decision, a
cross-project dependency and a private section.
"""

import tempfile
import unittest
from pathlib import Path

from notes import load_raw_notes, parse_raw_note, split_people
from offline import build, find_project, first_sentence, project_names, strip_meeting_words

SAMPLES = Path(__file__).resolve().parent.parent / "sample-notes"


def write(folder, name, text):
    path = Path(folder) / name
    path.write_text(text, encoding="utf-8")
    return path


class RawNoteTest(unittest.TestCase):
    def test_reads_title_date_people_and_bullets(self):
        with tempfile.TemporaryDirectory() as folder:
            path = write(
                folder,
                "2026-09-01-kickoff.md",
                "# Checkout kickoff\n\nDate: 2026-09-02\nAttendees: Priya Shah, Marcus Lee\n"
                "\n## Decisions\n\n- Remove guest checkout.\n\n## Private\n\n- Marcus is tired.\n",
            )
            raw = parse_raw_note(path)

        self.assertEqual(raw.title, "Checkout kickoff")
        self.assertEqual(raw.date, "2026-09-02")  # the Date line beats the file name
        self.assertEqual(raw.people, ["Priya Shah", "Marcus Lee"])
        self.assertEqual(raw.section("Decisions").bullets, ["Remove guest checkout."])
        self.assertTrue(raw.section("Private").is_private)
        self.assertFalse(raw.section("Decisions").is_private)

    def test_falls_back_to_the_date_in_the_file_name(self):
        with tempfile.TemporaryDirectory() as folder:
            path = write(folder, "2026-09-05-sync.md", "# Sync\n\n## Notes\n\n- All fine.\n")
            self.assertEqual(parse_raw_note(path).date, "2026-09-05")

    def test_an_owner_is_recorded_as_the_owner(self):
        with tempfile.TemporaryDirectory() as folder:
            path = write(folder, "2026-09-10-deals.md", "# Deals\n\nOwner: Jordan Kim\n")
            raw = parse_raw_note(path)
            self.assertEqual(raw.role("Jordan Kim"), "owner")

    def test_splitting_a_list_of_people(self):
        self.assertEqual(split_people("Priya Shah, Marcus Lee and Ana Ruiz"),
                         ["Priya Shah", "Marcus Lee", "Ana Ruiz"])

    def test_notes_come_back_oldest_first(self):
        dates = [raw.date for raw in load_raw_notes(SAMPLES)]
        self.assertEqual(dates, sorted(dates))

    def test_a_missing_folder_is_not_an_error(self):
        self.assertEqual(load_raw_notes(SAMPLES / "nope"), [])


class TitleTest(unittest.TestCase):
    def test_meeting_words_come_off_a_title(self):
        self.assertEqual(strip_meeting_words("Checkout redesign kickoff"), "Checkout redesign")

    def test_a_title_that_is_only_a_meeting_word_is_kept(self):
        self.assertEqual(strip_meeting_words("Review"), "Review")

    def test_first_sentence_of_a_bullet(self):
        self.assertEqual(
            first_sentence("Keep guest checkout. This reverses the earlier decision."),
            "Keep guest checkout",
        )

    def test_short_names_give_way_to_longer_ones(self):
        raws = load_raw_notes(SAMPLES)
        names = project_names(raws)
        self.assertIn("Checkout redesign", names)
        self.assertIn("Weekly deals email", names)
        self.assertNotIn("Checkout", names)  # swallowed by "Checkout redesign"

    def test_a_note_is_matched_to_the_project_its_text_uses(self):
        raws = {raw.source: raw for raw in load_raw_notes(SAMPLES)}
        names = project_names(list(raws.values()))
        self.assertEqual(
            find_project(raws["2026-09-08-checkout-design-review.md"], names),
            "Checkout redesign",
        )


class BuildTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.brain, cls.report = build(load_raw_notes(SAMPLES))

    def test_every_sample_note_was_read(self):
        self.assertEqual(self.report.notes_read, 4)
        self.assertEqual(self.report.skipped, [])

    def test_people_projects_and_decisions_all_appear(self):
        self.assertIn("people/marcus-lee", self.brain)
        self.assertIn("projects/checkout-redesign", self.brain)
        self.assertIn("decisions/keep-guest-checkout", self.brain)

    def test_the_reversed_decision_points_both_ways(self):
        new = self.brain["decisions/keep-guest-checkout"]
        old = self.brain["decisions/remove-guest-checkout"]
        self.assertEqual(new.replaces, old.id)
        self.assertEqual(old.replaced_by, new.id)

    def test_an_owner_is_not_described_as_an_attendee(self):
        jordan = self.brain["people/jordan-kim"]
        self.assertTrue(any(fact.text.startswith("Owns") for fact in jordan.facts))

    def test_private_bullets_stay_private(self):
        marcus = self.brain["people/marcus-lee"]
        private = [fact.text for fact in marcus.facts if fact.private]
        self.assertTrue(any("Search team" in text for text in private))
        self.assertTrue(all("Search team" not in fact.text for fact in marcus.public_facts()))

    def test_a_private_fact_adds_no_links(self):
        # Marcus's private lines mention nobody else, so his only person link
        # comes from the public half of the 1:1.
        marcus = self.brain["people/marcus-lee"]
        self.assertEqual([link for link in marcus.links if link.startswith("people/")],
                         ["people/priya-shah"])

    def test_every_fact_knows_where_it_came_from(self):
        sources = {Path(SAMPLES / fact.source).name for note in self.brain.values()
                   for fact in note.facts}
        self.assertTrue(sources.issubset({path.name for path in SAMPLES.glob("*.md")}))

    def test_reading_the_same_notes_twice_changes_nothing(self):
        again, _ = build(load_raw_notes(SAMPLES), self.brain)
        self.assertEqual(
            {note_id: note.render() for note_id, note in again.items()},
            {note_id: note.render() for note_id, note in self.brain.items()},
        )

    def test_a_bullet_nobody_can_place_is_reported_not_dropped(self):
        with tempfile.TemporaryDirectory() as folder:
            write(folder, "orphan.md", "# Stray thoughts\n\n## Ideas\n\n- Something happened.\n")
            _, report = build(load_raw_notes(folder))
            self.assertEqual(len(report.skipped), 1)
            self.assertIn("no date", report.skipped[0]["why"])


if __name__ == "__main__":
    unittest.main()
