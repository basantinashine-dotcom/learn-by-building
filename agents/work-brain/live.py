"""Building a brain with Claude reading the notes.

The rules in ``offline.py`` can find dates and names. They cannot tell that
"the Add to cart button drops people into checkout" ties one project to
another. That is the job this reader gives the model.

What the model is trusted with, and what it is not, is the whole design:

* it decides **what a note means**: which facts matter, who or what each one
  is about, which notes connect, which decision overturns which
* it decides **nothing about truth**. Every fact must come with a ``quote``,
  copied word for word from the note. If the quote is not in the note, the
  fact is thrown away and recorded in the report.

That check is cheap, mechanical, and catches the failure that matters most: a
confident sentence about something nobody wrote down. The model can still be
wrong about meaning, and a wrong fact with a real quote will get through. But
it cannot invent an event out of nothing, which is the failure people actually
get burned by.

Privacy is decided here too, not by the model. If a quote sits under a private
heading, the fact is private whatever the model said.

The Anthropic client is passed in, never created here, so the tests can drive
the whole reader with a fake client and no API key.
"""

import json
import re

from brain import BrainError, Fact
from notes import PRIVATE_HEADINGS
from offline import BrainBuilder

MODEL = "claude-opus-5"
MAX_TOKENS = 4000

# One note is one request. A very long note is cut rather than refused: a
# truncated reading of a long note beats no reading at all, and the report says
# it happened.
MAX_NOTE_CHARS = 20000

# A ceiling on what one note may add, so a runaway answer cannot fill the brain.
MAX_FACTS_PER_NOTE = 40

SYSTEM = """You turn a work note into memory: small facts about people, \
projects and decisions.

For each fact, give:
- subject_type: person, project or decision
- subject_title: the name of that person, project or decision, written the way \
the team writes it. Reuse a title from "Already in the brain" whenever the note \
means the same thing, so the memory does not split in two.
- text: one plain sentence someone could read a year from now, understandable \
without the note in front of them. Say who did what, not "he said it was fine".
- quote: the sentence from the note that this fact comes from, copied exactly, \
character for character. If you cannot copy a supporting sentence, do not \
include the fact.
- date: the date the fact was true, YYYY-MM-DD. Use the note's date unless the \
note gives another one.
- connects: other people, projects or decisions this fact ties the subject to, \
including ties the note only implies, such as one project waiting on another.
- replaces_decision: for a decision that overturns an earlier one, the title of \
the decision it overturns.

Rules:
- A decision is a choice the team made. A launch date or an owner is a fact \
about the project, not a decision of its own.
- Give a project facts about itself, not only about the people in the room.
- Prefer few good facts over many thin ones. Skip pleasantries and scheduling.
- Never add anything the note does not support."""

TOOL = {
    "name": "remember",
    "description": "Record the facts worth remembering from this note.",
    "input_schema": {
        "type": "object",
        "properties": {
            "facts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "subject_type": {
                            "type": "string",
                            "enum": ["person", "project", "decision"],
                        },
                        "subject_title": {"type": "string"},
                        "text": {"type": "string"},
                        "quote": {"type": "string"},
                        "date": {"type": "string"},
                        "connects": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "type": {
                                        "type": "string",
                                        "enum": ["person", "project", "decision"],
                                    },
                                    "title": {"type": "string"},
                                },
                                "required": ["type", "title"],
                            },
                        },
                        "replaces_decision": {"type": "string"},
                    },
                    "required": ["subject_type", "subject_title", "text", "quote", "date"],
                },
            }
        },
        "required": ["facts"],
    },
}


def normalise(text):
    """Collapse whitespace so a quote can be compared to the note fairly."""
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


def private_texts(raw):
    """Every bullet that sits under a private heading, normalised."""
    return [
        normalise(bullet)
        for section, bullet in raw.bullets(private=True)
    ]


def is_private_quote(quote, private_bullets):
    """True when a quote comes from a private part of the note."""
    wanted = normalise(quote)
    if not wanted:
        return False
    return any(wanted in bullet or bullet in wanted for bullet in private_bullets)


def prompt_for(raw, known_titles):
    """The user message for one note: the note itself, plus what we know."""
    known = "\n".join(f"- {title}" for title in known_titles) or "- (nothing yet)"
    body = raw.text[:MAX_NOTE_CHARS]
    return (
        f"Already in the brain:\n{known}\n\n"
        f"Note file: {raw.source}\n"
        f"Note date: {raw.date or 'unknown'}\n\n"
        f"---\n{body}\n---"
    )


def ask_model(client, raw, known_titles):
    """One request, one note. Returns the list of facts the model proposed."""
    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM,
        tools=[TOOL],
        tool_choice={"type": "tool", "name": TOOL["name"]},
        messages=[{"role": "user", "content": prompt_for(raw, known_titles)}],
    )
    for block in response.content:
        if getattr(block, "type", "") == "tool_use" and block.name == TOOL["name"]:
            data = block.input
            if isinstance(data, str):  # some clients hand back raw JSON
                data = json.loads(data)
            return data.get("facts", [])
    return []


def read_note(builder, raw, client):
    """Ask the model to read one note, then check and store what it says."""
    known_titles = sorted(note.title for note in builder.brain.values())
    try:
        proposed = ask_model(client, raw, known_titles)
    except Exception as error:  # a failed note must not lose the rest
        builder.report.skip(raw.source, raw.title, f"the model call failed: {error}")
        return

    if len(raw.text) > MAX_NOTE_CHARS:
        builder.report.skip(raw.source, raw.title, "note was too long and was cut short")

    private_bullets = private_texts(raw)
    note_text = normalise(raw.text)
    kept = 0

    for item in proposed[:MAX_FACTS_PER_NOTE]:
        text = (item.get("text") or "").strip()
        quote = (item.get("quote") or "").strip()

        # The one check the model cannot talk its way past.
        if not quote or normalise(quote) not in note_text:
            builder.report.skip(raw.source, text or quote, "quote is not in the note")
            continue

        try:
            subject = builder.note(item.get("subject_type", ""), item.get("subject_title", ""))
            fact = Fact(
                date=item.get("date") or raw.date,
                text=text,
                source=raw.source,
                private=is_private_quote(quote, private_bullets),
            )
        except BrainError as error:
            builder.report.skip(raw.source, text, str(error))
            continue

        if subject.add(fact):
            builder.report.facts_added += 1
        kept += 1

        if not fact.private:
            # As in the rule-based reader, a private fact never draws a line
            # between two notes: the line itself would give it away.
            for other in item.get("connects") or []:
                try:
                    builder.connect(subject, builder.note(other.get("type", ""), other.get("title", "")))
                except BrainError as error:
                    builder.report.skip(raw.source, str(other), str(error))

        replaced = (item.get("replaces_decision") or "").strip()
        if replaced and subject.type == "decision":
            try:
                earlier = builder.note("decision", replaced)
            except BrainError as error:
                builder.report.skip(raw.source, replaced, str(error))
                continue
            if earlier is not subject:
                subject.replaces = earlier.id
                earlier.replaced_by = subject.id
                builder.connect(subject, earlier)

    if len(proposed) > MAX_FACTS_PER_NOTE:
        builder.report.skip(
            raw.source, raw.title, f"kept the first {MAX_FACTS_PER_NOTE} facts of {len(proposed)}"
        )
    if not kept:
        builder.report.skip(raw.source, raw.title, "nothing usable came back for this note")

    builder.report.notes_read += 1


def build(raw_notes, client, brain=None):
    """Read every raw note with the model, oldest first.

    Notes are read in order and each request is told what is already in the
    brain, so the second mention of a project lands in the note the first one
    created instead of starting a new one.
    """
    builder = BrainBuilder(brain)
    for raw in raw_notes:
        read_note(builder, raw, client)
    return builder.brain, builder.report


def make_client(api_key=None):
    """Create an Anthropic client, importing the SDK only when it is needed.

    Offline mode must keep working on a machine with no SDK installed, so the
    import lives here rather than at the top of the file.
    """
    import anthropic

    return anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
