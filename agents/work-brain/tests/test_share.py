"""Tests for sharing: both layers of the guard, and the summary itself.

The test that matters most is ``test_a_leaked_sentence_is_cut``: it hands the
checker a draft that already contains a private fact, as though layer one had
failed, and proves layer two still catches it.
"""

import unittest
from pathlib import Path

from brain import Fact, Note
from notes import load_raw_notes
from offline import build
from share import (
    find_leaks,
    gather,
    leaks,
    offline_summary,
    private_facts,
    public_brain,
    redact,
    split_sentences,
    summarise,
)

SAMPLES = Path(__file__).resolve().parent.parent / "sample-notes"
SECRET = "Marcus is thinking about moving to the Search team next quarter."


class TextBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class Response:
    def __init__(self, blocks):
        self.content = blocks


class FakeClient:
    def __init__(self, draft):
        self.draft = draft
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return Response([TextBlock(self.draft)])


def sample_brain():
    brain, _ = build(load_raw_notes(SAMPLES))
    return brain


class PublicBrainTest(unittest.TestCase):
    def setUp(self):
        self.brain = sample_brain()

    def test_the_real_brain_has_private_facts(self):
        self.assertTrue(private_facts(self.brain))

    def test_the_public_copy_has_none(self):
        self.assertEqual(private_facts(public_brain(self.brain)), [])

    def test_the_public_copy_keeps_everything_else(self):
        public = public_brain(self.brain)
        self.assertEqual(sorted(public), sorted(self.brain))
        self.assertEqual(
            public["decisions/keep-guest-checkout"].replaces,
            self.brain["decisions/keep-guest-checkout"].replaces,
        )

    def test_editing_the_copy_does_not_touch_the_brain(self):
        public = public_brain(self.brain)
        public["people/marcus-lee"].facts.clear()
        self.assertTrue(self.brain["people/marcus-lee"].facts)


class LeakCheckTest(unittest.TestCase):
    def setUp(self):
        self.brain = sample_brain()

    def test_the_secret_itself_is_caught(self):
        self.assertTrue(find_leaks(SECRET, self.brain))

    def test_a_reworded_secret_is_caught(self):
        reworded = "Marcus may want a move to Search soon."
        self.assertTrue(find_leaks(reworded, self.brain))

    def test_a_full_paraphrase_is_not_caught(self):
        # A known limit, written down rather than hoped away. Layer two compares
        # words; this sentence shares none with the private fact. Layer one, not
        # this check, is what keeps the secret out of the draft.
        paraphrase = "Marcus may not be around for long."
        self.assertEqual(find_leaks(paraphrase, self.brain), [])

    def test_an_innocent_sentence_is_not_caught(self):
        clean = "Apple Pay is in scope and the launch target is 2026-10-20."
        self.assertEqual(find_leaks(clean, self.brain), [])

    def test_a_single_shared_word_is_not_a_leak(self):
        self.assertEqual(leaks("Marcus is on the team.", private_facts(self.brain)), [])

    def test_a_leaked_sentence_is_cut_and_the_rest_kept(self):
        draft = f"Checkout launches on 2026-10-20. {SECRET} Apple Pay is in scope."
        text, removed = redact(draft, self.brain)

        self.assertNotIn("Search team", text)
        self.assertIn("2026-10-20", text)
        self.assertIn("Apple Pay", text)
        self.assertEqual(len(removed), 1)

    def test_bullet_lines_are_checked_whole(self):
        draft = f"- {SECRET}\n- Apple Pay is in scope."
        text, removed = redact(draft, self.brain)
        self.assertEqual(len(removed), 1)
        self.assertIn("Apple Pay", text)

    def test_sentences_split_on_full_stops_and_bullets(self):
        self.assertEqual(len(split_sentences("One. Two.\n- Three\n\n")), 3)

    def test_a_brain_with_no_secrets_cuts_nothing(self):
        note = Note(type="project", title="Open project")
        note.add(Fact(date="2026-09-01", text="All public.", source="a.md"))
        text, removed = redact("All public.", {note.id: note})
        self.assertEqual((text, removed), ("All public.", []))


class GatherTest(unittest.TestCase):
    def setUp(self):
        self.brain = sample_brain()

    def test_it_finds_facts_about_the_topic(self):
        rows = gather(self.brain, "checkout redesign")
        self.assertTrue(rows)
        self.assertTrue(any("checkout" in note.title.lower() for _, note, _ in rows))

    def test_it_never_gathers_a_private_fact(self):
        rows = gather(self.brain, "Marcus")
        self.assertTrue(all(not fact.private for _, _, fact in rows))
        self.assertTrue(all("Search team" not in fact.text for _, _, fact in rows))

    def test_facts_come_back_newest_first(self):
        dates = [date for date, _, _ in gather(self.brain, "checkout redesign")]
        self.assertEqual(dates, sorted(dates, reverse=True))

    def test_an_overturned_decision_is_labelled(self):
        rows = gather(self.brain, "guest checkout")
        text = offline_summary(rows, "guest checkout")
        self.assertIn("no longer holds", text)


class SummariseTest(unittest.TestCase):
    def setUp(self):
        self.brain = sample_brain()

    def test_offline_mode_lists_the_facts(self):
        result = summarise(self.brain, "checkout redesign")
        self.assertEqual(result["mode"], "offline")
        self.assertIn("2026-10-20", result["text"])
        self.assertTrue(result["used"])

    def test_offline_mode_shares_nothing_private(self):
        result = summarise(self.brain, "Marcus")
        self.assertNotIn("Search team", result["text"])
        self.assertNotIn("stressed", result["text"])

    def test_live_mode_is_only_given_public_facts(self):
        client = FakeClient("Checkout launches 2026-10-20 with Apple Pay.")
        summarise(self.brain, "Marcus", client=client)
        sent = client.calls[0]["messages"][0]["content"]
        self.assertNotIn("Search team", sent)
        self.assertNotIn("stressed", sent)

    def test_a_model_that_leaks_anyway_is_caught(self):
        # Layer one has failed by the time this draft exists. Layer two holds.
        client = FakeClient(f"Checkout is on track. {SECRET}")
        result = summarise(self.brain, "checkout redesign", client=client)

        self.assertNotIn("Search team", result["text"])
        self.assertIn("Checkout is on track.", result["text"])
        self.assertEqual(len(result["removed"]), 1)

    def test_a_draft_that_is_all_leak_leaves_nothing(self):
        client = FakeClient(SECRET)
        result = summarise(self.brain, "checkout redesign", client=client)
        self.assertIn("Nothing safe to share", result["text"])

    def test_every_fact_used_names_its_source(self):
        result = summarise(self.brain, "checkout redesign")
        self.assertTrue(all(row["source"].endswith(".md") for row in result["used"]))

    def test_a_topic_with_nothing_to_say_says_so(self):
        result = summarise(self.brain, "zebra")
        self.assertEqual(result["mode"], "empty")
        self.assertEqual(result["used"], [])


if __name__ == "__main__":
    unittest.main()
