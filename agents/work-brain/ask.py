"""Asking the brain a question.

Two ways to answer, and the difference is worth understanding.

**Offline** (``offline_answer``) does no thinking at all. It scores notes by
word overlap with the question and prints the matching facts, newest first,
with their sources. It cannot write a sentence, but it can never be wrong: what
you read is what the brain holds.

**Live** (``answer``) hands Claude two tools, ``search_brain`` and
``open_note``, and lets it look things up for itself, the way you would: search,
read a note, follow a link, read another, then answer. The alternative, stuffing
the whole brain into one prompt, is simpler and works fine at four notes. It
stops working at four hundred, and it never shows you what the answer was based
on. A tool loop leaves a trail: every note the model opened is recorded, so an
answer can be checked against the notes it actually read.

Both are told about ``replaces`` and ``replaced_by``, so "do we have guest
checkout?" can answer with today's decision *and* the one it overturned.

Answers here are for you, on your own machine, so private facts are included
and marked. Sharing with other people is a different job, in ``share.py``.
"""

import json
import re

from brain import FOLDERS

MODEL = "claude-opus-5"
MAX_TOKENS = 2000

# How many turns the model may take before it must answer. A question needs
# two or three searches; a loop that wants more has stopped converging.
MAX_TURNS = 8

# How many notes a search hands back. Enough to answer, few enough to read.
SEARCH_LIMIT = 6

STOP_WORDS = {
    "the", "a", "an", "and", "or", "of", "to", "for", "in", "on", "is", "are",
    "was", "were", "be", "do", "does", "did", "we", "our", "us", "this", "that",
    "it", "at", "by", "with", "from", "what", "who", "when", "why", "how",
    "about", "any", "have", "has", "had", "can", "could", "should", "would",
}

SYSTEM = """You answer questions from a work brain: small notes about people, \
projects and decisions, each fact carrying a date and the note it came from.

Work like this:
1. search_brain for the question's subject.
2. open_note on anything that looks relevant, and follow its links.
3. Answer only from what you read.

Rules:
- Every claim in your answer names the note it came from, like (people/marcus-lee).
- Facts have dates and decisions can be replaced. When a decision was \
overturned, say what holds now and what it changed from.
- If the brain does not answer the question, say so and say what it does have. \
Never fill a gap with a guess.
- A fact marked private is yours alone. You may use it, but say "(private)" \
after it so the reader knows not to pass it on.
- Answer in a few sentences. No preamble."""


def key_words(text):
    """The words worth matching on, lower-cased."""
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {word for word in words if word not in STOP_WORDS and len(word) > 2}


def score_note(note, wanted, include_private=True):
    """How well one note matches a question.

    A title hit counts double: a note called "Keep guest checkout" is more
    likely to be the answer than one that mentions checkout in passing.
    """
    facts = note.facts if include_private else note.public_facts()
    if not facts and not note.title:
        return 0
    title_hits = len(wanted & key_words(note.title))
    fact_hits = len(wanted & key_words(" ".join(fact.text for fact in facts)))
    return title_hits * 2 + fact_hits


def search(brain, query, limit=SEARCH_LIMIT, include_private=True):
    """The notes that best match a question, best first."""
    wanted = key_words(query)
    if not wanted:
        return []
    scored = [
        (score_note(note, wanted, include_private), note)
        for note in brain.values()
    ]
    hits = [(score, note) for score, note in scored if score]
    hits.sort(key=lambda pair: (-pair[0], -len(pair[1].updated), pair[1].id))
    return [note for _, note in hits[:limit]]


def expand(brain, notes, limit=12):
    """Add the notes that the hits link to.

    A project note is often the best match for a question while the answer
    sits one hop away, in a decision linked to it. Following links once is
    cheap and finds those; following them twice pulls in half the brain.
    """
    found = list(notes)
    for note in notes:
        for link in note.links:
            other = brain.get(link)
            if other is not None and other not in found and len(found) < limit:
                found.append(other)
    return found


def render_note(note, include_private=True):
    """One note as text for the model: header lines, then dated facts."""
    facts = note.facts if include_private else note.public_facts()
    lines = [f"# {note.title} ({note.id})"]
    if note.replaces:
        lines.append(f"replaces: {note.replaces}")
    if note.replaced_by:
        lines.append(f"REPLACED BY: {note.replaced_by} (this is no longer what holds)")
    if note.links:
        lines.append(f"links: {', '.join(note.links)}")
    lines.append("")
    for fact in sorted(facts, key=lambda item: item.date):
        mark = " [private]" if fact.private else ""
        lines.append(f"- {fact.date}{mark} {fact.text} (from {fact.source})")
    if not facts:
        lines.append("- (no facts)")
    return "\n".join(lines)


def summarise(note, include_private=True):
    """One line about a note, for search results."""
    facts = note.facts if include_private else note.public_facts()
    return f"{note.id} — {note.title} ({len(facts)} facts, newest {note.updated or 'none'})"


TOOLS = [
    {
        "name": "search_brain",
        "description": "Find notes matching some words. Returns note ids and titles.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
    {
        "name": "open_note",
        "description": "Read one note in full, by id, e.g. people/marcus-lee.",
        "input_schema": {
            "type": "object",
            "properties": {"note_id": {"type": "string"}},
            "required": ["note_id"],
        },
    },
]


class BrainTools:
    """The two tools, and a record of everything they were asked for.

    The record is the point: an answer you cannot trace is an answer you have
    to take on faith.
    """

    def __init__(self, brain, include_private=True):
        self.brain = brain
        self.include_private = include_private
        self.opened = []
        self.searches = []

    def run(self, name, args):
        if name == "search_brain":
            query = (args or {}).get("query", "")
            self.searches.append(query)
            hits = search(self.brain, query, include_private=self.include_private)
            if not hits:
                return f"No notes match {query!r}."
            return "\n".join(summarise(note, self.include_private) for note in hits)

        if name == "open_note":
            note_id = (args or {}).get("note_id", "").strip().strip("()")
            note = self.brain.get(note_id) or self.brain.get(note_id.rstrip("/"))
            if not note:
                known = ", ".join(sorted(self.brain)[:10]) or "nothing yet"
                return f"No note called {note_id!r}. Some ids: {known}."
            if note_id not in self.opened:
                self.opened.append(note_id)
            return render_note(note, self.include_private)

        return f"No tool called {name!r}."


def answer(client, brain, question, include_private=True):
    """Let the model search the brain and answer, and keep the trail.

    Returns the answer text, the notes it opened, and the searches it ran.
    """
    tools = BrainTools(brain, include_private)
    messages = [{"role": "user", "content": question}]
    text = ""

    for _ in range(MAX_TURNS):
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM,
            tools=TOOLS,
            messages=messages,
        )
        blocks = list(response.content)
        said = " ".join(
            block.text for block in blocks if getattr(block, "type", "") == "text"
        ).strip()
        if said:
            text = said

        calls = [block for block in blocks if getattr(block, "type", "") == "tool_use"]
        if not calls:
            break

        messages.append({"role": "assistant", "content": blocks})
        messages.append({
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": call.id,
                    "content": tools.run(call.name, call.input),
                }
                for call in calls
            ],
        })
    else:
        text = text or "I had to stop before finishing that one. Try a narrower question."

    return {
        "text": text or "I could not answer that from the brain.",
        "opened": tools.opened,
        "searches": tools.searches,
        "cited": cited_notes(text, brain),
    }


def cited_notes(text, brain):
    """Note ids the answer mentions, so a reader can check them.

    The model is asked to cite; this is where we find out whether it did.
    """
    folders = "|".join(FOLDERS.values())
    found = re.findall(rf"\b(?:{folders})/[a-z0-9-]+", text or "")
    return [note_id for note_id in dict.fromkeys(found) if note_id in brain]


def offline_answer(brain, question, include_private=True):
    """Answer with no model: the matching facts, newest first, with sources."""
    hits = search(brain, question, include_private=include_private)
    if not hits:
        return {
            "text": "Nothing in the brain matches that.",
            "opened": [],
            "searches": [question],
            "cited": [],
        }

    lines = ["The brain has these, newest first. (Offline mode does not write answers.)"]
    for note in hits:
        lines.append("")
        lines.append(f"{note.title} ({note.id})")
        if note.replaced_by:
            lines.append(f"  no longer holds, replaced by {note.replaced_by}")
        facts = note.facts if include_private else note.public_facts()
        for fact in sorted(facts, key=lambda item: item.date, reverse=True)[:4]:
            mark = " (private)" if fact.private else ""
            lines.append(f"  {fact.date}{mark} {fact.text} [{fact.source}]")

    return {
        "text": "\n".join(lines),
        "opened": [note.id for note in hits],
        "searches": [question],
        "cited": [note.id for note in hits],
    }
