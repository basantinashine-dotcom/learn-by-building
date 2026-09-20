"""Tests for the Claude reader, driven by a fake client and no API key.

The point of these tests is not that the model is clever. It is that whatever
the model sends back, the checks around it hold: a fact without a real quote
never enters the brain, and a fact from a private section is private even when
the model forgets to say so.
"""

import tempfile
import unittest
from pathlib import Path

import live
from live import build, is_private_quote, private_texts, prompt_for
from notes import load_raw_notes, parse_raw_note

NOTE = """# Checkout design review

Date: 2026-09-08
Attendees: Priya Shah, Marcus Lee

## Discussion

- Priya shared the data: 41% of first-time buyers use guest checkout.

## Decisions

- Keep guest checkout.

## Private

- Marcus is thinking about moving to the Search team next quarter.
"""


class Block:
    """One tool_use block, shaped like the SDK's."""

    def __init__(self, facts, name="remember"):
        self.type = "tool_use"
        self.name = name
        self.input = {"facts": facts}


class Response:
    def __init__(self, blocks):
        self.content = blocks


class FakeClient:
    """Answers each request with the next canned reply, and records the calls."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return Response([Block(reply)] if isinstance(reply, list) else reply)


def fact(**overrides):
    item = {
        "subject_type": "decision",
        "subject_title": "Keep guest checkout",
        "text": "The team kept guest checkout.",
        "quote": "Keep guest checkout.",
        "date": "2026-09-08",
    }
    item.update(overrides)
    return item


def write_note(folder, text=NOTE, name="2026-09-08-review.md"):
    path = Path(folder) / name
    path.write_text(text, encoding="utf-8")
    return path


def read_with(replies, text=NOTE):
    """Run the reader over one note with canned model replies."""
    with tempfile.TemporaryDirectory() as folder:
        write_note(folder, text)
        return build(load_raw_notes(folder), FakeClient(replies))


class QuoteCheckTest(unittest.TestCase):
    def test_a_fact_with_a_real_quote_is_kept(self):
        brain, report = read_with([[fact()]])
        self.assertIn("decisions/keep-guest-checkout", brain)
        self.assertEqual(report.facts_added, 1)
        self.assertEqual(report.skipped, [])

    def test_an_invented_quote_is_thrown_away(self):
        brain, report = read_with([[fact(quote="We agreed to delete the company.")]])
        self.assertEqual(brain, {})
        self.assertEqual(report.skipped[0]["why"], "quote is not in the note")

    def test_a_missing_quote_is_thrown_away(self):
        _, report = read_with([[fact(quote="")]])
        self.assertEqual(report.skipped[0]["why"], "quote is not in the note")

    def test_a_quote_is_matched_despite_spacing(self):
        brain, _ = read_with([[fact(quote="  Keep   guest    checkout. ")]])
        self.assertIn("decisions/keep-guest-checkout", brain)

    def test_one_bad_fact_does_not_lose_the_good_ones(self):
        brain, report = read_with([[fact(quote="invented"), fact()]])
        self.assertEqual(report.facts_added, 1)
        self.assertEqual(len(report.skipped), 1)


class PrivacyTest(unittest.TestCase):
    def test_a_private_quote_makes_a_private_fact(self):
        brain, _ = read_with([[fact(
            subject_type="person",
            subject_title="Marcus Lee",
            text="Marcus may move to the Search team.",
            quote="Marcus is thinking about moving to the Search team next quarter.",
        )]])
        marcus = brain["people/marcus-lee"]
        self.assertTrue(marcus.facts[0].private)
        self.assertEqual(marcus.public_facts(), [])

    def test_a_private_fact_creates_no_links(self):
        brain, _ = read_with([[fact(
            subject_type="person",
            subject_title="Marcus Lee",
            quote="Marcus is thinking about moving to the Search team next quarter.",
            connects=[{"type": "project", "title": "Checkout redesign"}],
        )]])
        self.assertEqual(brain["people/marcus-lee"].links, [])

    def test_a_public_fact_still_links(self):
        brain, _ = read_with([[fact(connects=[{"type": "project", "title": "Checkout redesign"}])]])
        self.assertEqual(
            brain["decisions/keep-guest-checkout"].links, ["projects/checkout-redesign"]
        )
        self.assertEqual(
            brain["projects/checkout-redesign"].links, ["decisions/keep-guest-checkout"]
        )

    def test_private_bullets_are_found_in_the_note(self):
        with tempfile.TemporaryDirectory() as folder:
            raw = parse_raw_note(write_note(folder))
        bullets = private_texts(raw)
        self.assertEqual(len(bullets), 1)
        self.assertTrue(is_private_quote("moving to the Search team", bullets))
        self.assertFalse(is_private_quote("Keep guest checkout.", bullets))


class ReversalTest(unittest.TestCase):
    def test_a_reversal_is_wired_both_ways(self):
        brain, _ = read_with([[fact(replaces_decision="Remove guest checkout")]])
        new = brain["decisions/keep-guest-checkout"]
        old = brain["decisions/remove-guest-checkout"]
        self.assertEqual(new.replaces, old.id)
        self.assertEqual(old.replaced_by, new.id)

    def test_a_decision_cannot_replace_itself(self):
        brain, _ = read_with([[fact(replaces_decision="Keep guest checkout")]])
        self.assertEqual(brain["decisions/keep-guest-checkout"].replaces, "")


class RobustnessTest(unittest.TestCase):
    def test_a_failed_call_is_reported_and_the_run_goes_on(self):
        with tempfile.TemporaryDirectory() as folder:
            write_note(folder, NOTE, "2026-09-08-review.md")
            write_note(folder, NOTE.replace("design review", "kickoff"), "2026-09-09-kickoff.md")
            client = FakeClient([RuntimeError("no credit"), [fact()]])
            brain, report = build(load_raw_notes(folder), client)

        self.assertIn("the model call failed", report.skipped[0]["why"])
        self.assertEqual(report.facts_added, 1)

    def test_an_unknown_subject_type_is_refused(self):
        _, report = read_with([[fact(subject_type="animal")]])
        self.assertIn("unknown note type", report.skipped[0]["why"])

    def test_a_fact_with_no_date_falls_back_to_the_note_date(self):
        brain, _ = read_with([[fact(date="")]])
        self.assertEqual(brain["decisions/keep-guest-checkout"].facts[0].date, "2026-09-08")

    def test_a_runaway_answer_is_capped(self):
        many = [fact(text=f"Fact number {index}.") for index in range(live.MAX_FACTS_PER_NOTE + 5)]
        _, report = read_with([many])
        self.assertTrue(any("kept the first" in skip["why"] for skip in report.skipped))

    def test_an_empty_answer_is_reported(self):
        _, report = read_with([[]])
        self.assertIn("nothing usable", report.skipped[0]["why"])


class PromptTest(unittest.TestCase):
    def test_the_prompt_carries_the_note_and_what_is_known(self):
        with tempfile.TemporaryDirectory() as folder:
            raw = parse_raw_note(write_note(folder))
        text = prompt_for(raw, ["Checkout redesign"])
        self.assertIn("Checkout redesign", text)
        self.assertIn("Keep guest checkout.", text)
        self.assertIn("2026-09-08", text)

    def test_a_long_note_is_cut(self):
        long_note = NOTE + "\n" + ("- padding\n" * 5000)
        with tempfile.TemporaryDirectory() as folder:
            raw = parse_raw_note(write_note(folder, long_note))
        self.assertLessEqual(len(prompt_for(raw, [])), live.MAX_NOTE_CHARS + 500)

    def test_the_model_is_made_to_use_the_tool(self):
        with tempfile.TemporaryDirectory() as folder:
            write_note(folder)
            client = FakeClient([[fact()]])
            build(load_raw_notes(folder), client)
        call = client.calls[0]
        self.assertEqual(call["tool_choice"], {"type": "tool", "name": "remember"})
        self.assertEqual(call["model"], live.MODEL)


if __name__ == "__main__":
    unittest.main()
