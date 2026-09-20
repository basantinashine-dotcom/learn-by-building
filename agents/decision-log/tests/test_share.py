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
    explain,
    find_decision,
    find_leaks,
    leaks,
    offline_explanation,
    private_facts,
    public_brain,
    redact,
    render_card,
    split_sentences,
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


class FindDecisionTest(unittest.TestCase):
    def setUp(self):
        self.brain = sample_brain()

    def test_an_exact_id_is_taken_as_given(self):
        found = find_decision(self.brain, "decisions/keep-guest-checkout")
        self.assertEqual(found.title, "Keep guest checkout")

    def test_words_find_the_decision_they_describe(self):
        self.assertEqual(find_decision(self.brain, "guest checkout").type, "decision")

    def test_a_person_is_never_returned_as_a_decision(self):
        found = find_decision(self.brain, "Marcus Lee")
        self.assertTrue(found is None or found.type == "decision")

    def test_nothing_matching_returns_nothing(self):
        self.assertIsNone(find_decision(self.brain, "zebra"))


class ExplainTest(unittest.TestCase):
    def setUp(self):
        self.brain = sample_brain()

    def test_offline_mode_leads_with_the_decision_and_its_reason(self):
        result = explain(self.brain, "guest checkout")
        self.assertEqual(result["mode"], "offline")
        self.assertIn("Keep guest checkout", result["text"])
        self.assertIn("41%", result["text"])
        self.assertTrue(result["used"])

    def test_it_says_what_the_decision_replaced(self):
        result = explain(self.brain, "decisions/keep-guest-checkout")
        self.assertIn("It replaced: Remove guest checkout", result["text"])

    def test_a_reversed_decision_says_it_no_longer_holds(self):
        result = explain(self.brain, "decisions/remove-guest-checkout")
        self.assertIn("no longer holds", result["text"])

    def test_the_card_carries_the_evidence(self):
        card = explain(self.brain, "guest checkout")["decision"]
        self.assertEqual(card["status"], "current")
        self.assertTrue(card["why"])
        self.assertTrue(card["history"])
        self.assertTrue(all(row["source"].endswith(".md") for row in card["why"]))

    def test_live_mode_is_only_given_public_facts(self):
        client = FakeClient("Guest checkout stays because 41% of new buyers use it.")
        explain(self.brain, "guest checkout", client=client)
        sent = client.calls[0]["messages"][0]["content"]
        self.assertIn("Why it was decided", sent)
        self.assertNotIn("Search team", sent)
        self.assertNotIn("stressed", sent)

    def test_a_model_that_leaks_anyway_is_caught(self):
        # Layer one has failed by the time this draft exists. Layer two holds.
        client = FakeClient(f"Guest checkout stays. {SECRET}")
        result = explain(self.brain, "guest checkout", client=client)

        self.assertNotIn("Search team", result["text"])
        self.assertIn("Guest checkout stays.", result["text"])
        self.assertEqual(len(result["removed"]), 1)

    def test_a_draft_that_is_all_leak_leaves_nothing(self):
        client = FakeClient(SECRET)
        result = explain(self.brain, "guest checkout", client=client)
        self.assertIn("Nothing safe to share", result["text"])

    def test_every_fact_used_names_its_source(self):
        result = explain(self.brain, "guest checkout")
        self.assertTrue(all(row["source"].endswith(".md") for row in result["used"]))

    def test_a_decision_nobody_has_made_says_so(self):
        result = explain(self.brain, "zebra")
        self.assertEqual(result["mode"], "empty")
        self.assertIsNone(result["decision"])

    def test_a_decision_with_no_recorded_reason_admits_it(self):
        from ask import decision_card

        note = self.brain["decisions/launch-target-2026-10-20"]
        card = decision_card(self.brain, note)
        self.assertEqual(card["why"], [])
        self.assertIn("the notes do not say", offline_explanation(card))
        self.assertIn("(the notes do not say)", render_card(card))


if __name__ == "__main__":
    unittest.main()
