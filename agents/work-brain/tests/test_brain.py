"""Tests for the note format: what is written must read back the same."""

import tempfile
import unittest
from pathlib import Path

from brain import (
    BrainError,
    Fact,
    Note,
    load_brain,
    load_note,
    parse_fact,
    parse_note,
    save_note,
    slugify,
)


def fact(date="2026-09-08", text="Guest checkout stays.", source="review.md", private=False):
    return Fact(date=date, text=text, source=source, private=private)


class FactTest(unittest.TestCase):
    def test_a_fact_needs_a_real_date(self):
        with self.assertRaises(BrainError):
            fact(date="last Tuesday")

    def test_a_fact_needs_a_source(self):
        with self.assertRaises(BrainError):
            fact(source="  ")

    def test_renders_as_one_line_with_its_source(self):
        self.assertEqual(
            fact().render(),
            "- 2026-09-08 | Guest checkout stays. | source: review.md",
        )

    def test_a_private_fact_says_so(self):
        self.assertTrue(fact(private=True).render().endswith("| private"))

    def test_a_separator_in_the_text_cannot_break_the_line(self):
        line = fact(text="cart | address | pay").render()
        self.assertEqual(parse_fact(line).text, "cart / address / pay")


class NoteTest(unittest.TestCase):
    def test_the_id_comes_from_the_type_and_title(self):
        note = Note(type="person", title="Marcus Lee")
        self.assertEqual(note.id, "people/marcus-lee")

    def test_an_unknown_type_is_refused(self):
        with self.assertRaises(BrainError):
            Note(type="animal", title="Cat")

    def test_updated_is_the_newest_fact(self):
        note = Note(type="project", title="Checkout redesign")
        note.add(fact(date="2026-09-01"))
        note.add(fact(date="2026-09-12", text="Apple Pay is blocked."))
        self.assertEqual(note.updated, "2026-09-12")

    def test_a_note_with_no_facts_has_no_date(self):
        self.assertEqual(Note(type="project", title="New thing").updated, "")

    def test_the_same_fact_is_not_stored_twice(self):
        note = Note(type="project", title="Checkout redesign")
        self.assertTrue(note.add(fact()))
        self.assertFalse(note.add(fact()))
        self.assertEqual(len(note.facts), 1)

    def test_a_repeated_fact_becomes_private_if_it_ever_was(self):
        note = Note(type="person", title="Marcus Lee")
        note.add(fact())
        note.add(fact(private=True))
        self.assertTrue(note.facts[0].private)
        self.assertEqual(note.public_facts(), [])

    def test_facts_are_kept_in_date_order(self):
        note = Note(type="project", title="Checkout redesign")
        note.add(fact(date="2026-09-12", text="Apple Pay is blocked."))
        note.add(fact(date="2026-09-01", text="Cart abandonment is 62%."))
        self.assertEqual([item.date for item in note.facts], ["2026-09-01", "2026-09-12"])

    def test_a_note_does_not_link_to_itself_or_repeat_a_link(self):
        note = Note(type="person", title="Priya Shah")
        self.assertTrue(note.link_to("projects/checkout-redesign"))
        self.assertFalse(note.link_to("projects/checkout-redesign"))
        self.assertFalse(note.link_to("people/priya-shah"))


class SlugTest(unittest.TestCase):
    def test_names_become_file_names(self):
        self.assertEqual(slugify("Checkout redesign"), "checkout-redesign")

    def test_accents_and_punctuation_fold_away(self):
        self.assertEqual(slugify("Ana Ruíz!"), "ana-ruiz")

    def test_a_title_with_no_letters_is_refused(self):
        with self.assertRaises(BrainError):
            slugify("!!!")


class RoundTripTest(unittest.TestCase):
    def build(self):
        note = Note(
            type="decision",
            title="Keep guest checkout",
            links=["projects/checkout-redesign"],
            replaces="decisions/remove-guest-checkout",
        )
        note.add(fact())
        note.add(fact(date="2026-09-12", text="Marcus may move teams.", private=True))
        return note

    def test_a_note_reads_back_the_same(self):
        original = self.build()
        copy = parse_note(original.render())
        self.assertEqual(copy.render(), original.render())
        self.assertEqual(copy.replaces, "decisions/remove-guest-checkout")
        self.assertEqual(copy.links, ["projects/checkout-redesign"])
        self.assertTrue(copy.facts[1].private)

    def test_lines_that_are_not_facts_are_skipped(self):
        text = self.build().render() + "\nnotes to self\n- not a fact\n"
        self.assertEqual(len(parse_note(text).facts), 2)

    def test_a_note_without_a_header_is_refused(self):
        with self.assertRaises(BrainError):
            parse_note("## Facts\n\n- 2026-09-08 | x | source: y.md")


class DiskTest(unittest.TestCase):
    def test_a_saved_brain_loads_back(self):
        with tempfile.TemporaryDirectory() as folder:
            note = Note(type="person", title="Marcus Lee")
            note.add(fact(text="Leads payments engineering."))
            path = save_note(folder, note)

            self.assertEqual(path, Path(folder) / "people" / "marcus-lee.md")
            self.assertEqual(load_note(path).title, "Marcus Lee")
            self.assertEqual(list(load_brain(folder)), ["people/marcus-lee"])

    def test_a_brain_that_does_not_exist_yet_is_empty(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(load_brain(Path(folder) / "brain"), {})


if __name__ == "__main__":
    unittest.main()
