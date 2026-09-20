"""Tests for search, the tool loop, and the offline answer.

The brain used here is built by the rule-based reader from the real sample
notes, so these tests check the thing people will actually ask questions of.
"""

import unittest
from pathlib import Path

import ask
from ask import BrainTools, answer, cited_notes, offline_answer, render_note, search
from notes import load_raw_notes
from offline import build

SAMPLES = Path(__file__).resolve().parent.parent / "sample-notes"


class TextBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class ToolBlock:
    def __init__(self, name, args, block_id="call_1"):
        self.type = "tool_use"
        self.name = name
        self.input = args
        self.id = block_id


class Response:
    def __init__(self, blocks):
        self.content = blocks


class FakeClient:
    """Replays canned turns and records what it was sent."""

    def __init__(self, turns):
        self.turns = list(turns)
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return Response(self.turns.pop(0) if self.turns else [TextBlock("Done.")])


def sample_brain():
    brain, _ = build(load_raw_notes(SAMPLES))
    return brain


class SearchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.brain = sample_brain()

    def test_finds_the_note_about_what_was_asked(self):
        hits = search(self.brain, "who owns the checkout redesign?")
        self.assertIn("projects/checkout-redesign", [note.id for note in hits])

    def test_a_title_match_beats_a_passing_mention(self):
        hits = search(self.brain, "guest checkout")
        self.assertTrue(hits[0].title.lower().endswith("guest checkout"))

    def test_a_question_of_only_common_words_finds_nothing(self):
        self.assertEqual(search(self.brain, "what is it about?"), [])

    def test_private_facts_can_be_left_out_of_the_score(self):
        with_private = search(self.brain, "Search team next quarter", include_private=True)
        without = search(self.brain, "Search team next quarter", include_private=False)
        self.assertIn("people/marcus-lee", [note.id for note in with_private])
        self.assertNotIn("people/marcus-lee", [note.id for note in without])


class RenderTest(unittest.TestCase):
    def setUp(self):
        self.brain = sample_brain()

    def test_an_overturned_decision_says_so(self):
        text = render_note(self.brain["decisions/remove-guest-checkout"])
        self.assertIn("REPLACED BY: decisions/keep-guest-checkout", text)
        self.assertIn("no longer what holds", text)

    def test_facts_carry_their_date_and_source(self):
        text = render_note(self.brain["people/priya-shah"])
        self.assertIn("2026-09-08", text)
        self.assertIn("(from 2026-09-08-checkout-design-review.md)", text)

    def test_private_facts_are_marked_and_can_be_hidden(self):
        marcus = self.brain["people/marcus-lee"]
        self.assertIn("[private]", render_note(marcus))
        self.assertNotIn("[private]", render_note(marcus, include_private=False))


class ToolTest(unittest.TestCase):
    def setUp(self):
        self.tools = BrainTools(sample_brain())

    def test_search_returns_note_ids(self):
        result = self.tools.run("search_brain", {"query": "apple pay"})
        self.assertIn("people/marcus-lee", result)
        self.assertEqual(self.tools.searches, ["apple pay"])

    def test_opening_a_note_records_it(self):
        self.tools.run("open_note", {"note_id": "people/marcus-lee"})
        self.assertEqual(self.tools.opened, ["people/marcus-lee"])

    def test_a_note_id_in_brackets_still_opens(self):
        self.assertIn("Marcus", self.tools.run("open_note", {"note_id": "(people/marcus-lee)"}))

    def test_an_unknown_note_suggests_real_ids(self):
        result = self.tools.run("open_note", {"note_id": "people/nobody"})
        self.assertIn("No note called", result)
        self.assertIn("people/", result)

    def test_an_unknown_tool_does_not_crash(self):
        self.assertIn("No tool called", self.tools.run("delete_everything", {}))

    def test_a_search_with_no_hits_says_so(self):
        self.assertIn("No notes match", self.tools.run("search_brain", {"query": "zebra"}))


class AnswerTest(unittest.TestCase):
    def setUp(self):
        self.brain = sample_brain()

    def test_the_model_can_search_then_answer(self):
        client = FakeClient([
            [ToolBlock("search_brain", {"query": "guest checkout"})],
            [ToolBlock("open_note", {"note_id": "decisions/keep-guest-checkout"}, "call_2")],
            [TextBlock("Guest checkout stays (decisions/keep-guest-checkout).")],
        ])
        result = answer(client, self.brain, "Do we have guest checkout?")

        self.assertIn("Guest checkout stays", result["text"])
        self.assertEqual(result["opened"], ["decisions/keep-guest-checkout"])
        self.assertEqual(result["searches"], ["guest checkout"])
        self.assertEqual(result["cited"], ["decisions/keep-guest-checkout"])

    def test_tool_results_are_sent_back_to_the_model(self):
        client = FakeClient([
            [ToolBlock("open_note", {"note_id": "people/marcus-lee"})],
            [TextBlock("Marcus leads payments.")],
        ])
        answer(client, self.brain, "What is Marcus working on?")

        second_call = client.calls[1]["messages"]
        self.assertEqual(second_call[-1]["role"], "user")
        self.assertEqual(second_call[-1]["content"][0]["type"], "tool_result")
        self.assertIn("Apple Pay", second_call[-1]["content"][0]["content"])

    def test_an_answer_with_no_tools_is_returned_as_is(self):
        client = FakeClient([[TextBlock("I could not find that.")]])
        result = answer(client, self.brain, "Who is the CEO?")
        self.assertEqual(result["opened"], [])
        self.assertEqual(result["cited"], [])

    def test_a_loop_that_never_stops_is_cut_off(self):
        turns = [[ToolBlock("search_brain", {"query": "checkout"}, f"call_{i}")]
                 for i in range(ask.MAX_TURNS + 2)]
        client = FakeClient(turns)
        result = answer(client, self.brain, "Tell me everything.")

        self.assertEqual(len(client.calls), ask.MAX_TURNS)
        self.assertIn("had to stop", result["text"])

    def test_private_facts_can_be_kept_out_of_the_tools(self):
        client = FakeClient([
            [ToolBlock("open_note", {"note_id": "people/marcus-lee"})],
            [TextBlock("He is on Apple Pay.")],
        ])
        answer(client, self.brain, "What is Marcus up to?", include_private=False)
        sent = client.calls[1]["messages"][-1]["content"][0]["content"]
        self.assertNotIn("Search team", sent)

    def test_only_real_note_ids_count_as_citations(self):
        self.assertEqual(cited_notes("see people/nobody and people/marcus-lee", self.brain),
                         ["people/marcus-lee"])


class OfflineAnswerTest(unittest.TestCase):
    def setUp(self):
        self.brain = sample_brain()

    def test_it_lists_matching_facts_with_sources(self):
        result = offline_answer(self.brain, "guest checkout")
        self.assertIn("guest checkout", result["text"].lower())
        self.assertIn(".md]", result["text"])
        self.assertTrue(result["cited"])

    def test_it_flags_a_decision_that_no_longer_holds(self):
        result = offline_answer(self.brain, "remove guest checkout")
        self.assertIn("no longer holds", result["text"])

    def test_nothing_matching_says_nothing_matching(self):
        result = offline_answer(self.brain, "zebra")
        self.assertIn("Nothing in the log", result["text"])

    def test_private_facts_can_be_left_out(self):
        result = offline_answer(self.brain, "Marcus", include_private=False)
        self.assertNotIn("Search team", result["text"])


if __name__ == "__main__":
    unittest.main()
