"""Building a brain with rules only: no AI, no API key, no network.

This reader is deliberately simple-minded. It looks at headings, bullets and
capitalised names, and follows fixed rules:

* people come from "Attendees:" and "Owner:" lines
* bullets under "Decisions" become decision notes
* a bullet that starts with someone's name becomes a fact about that person
* everything else becomes a fact about whatever the note is mainly about
* bullets under "Private" are marked private

It exists for three reasons. It lets anyone run Work Brain with no API key, it
gives the tests something fast and predictable to check, and it is the baseline
the Claude reader in ``live.py`` has to beat. If the rules already do the job,
the model is not earning its place.

Where the rules give up, they say so rather than guessing: see ``Report``.
"""

import re
from dataclasses import dataclass, field

from brain import Fact, Note, slugify

# Words that turn a project name into a meeting name. "Checkout redesign
# kickoff" is a meeting about the "Checkout redesign" project.
MEETING_WORDS = (
    "kickoff",
    "kick-off",
    "design review",
    "review",
    "sync",
    "standup",
    "stand-up",
    "retro",
    "retrospective",
    "planning",
    "check-in",
    "update",
    "meeting",
    "notes",
)

# "1:1 with Marcus" is about a person, not a project.
ONE_ON_ONE = re.compile(r"^(1:1|one[- ]on[- ]one|catch[- ]?up)\s+with\s+(.+)", re.IGNORECASE)

# "Ana: design the screen" and "Marcus said the payment code is old".
LEADING_NAME = re.compile(r"^([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s*(?::|\b)")

# A decision bullet that overturns an earlier one.
REVERSAL_WORDS = ("reverses", "replaces", "overturns", "undoes")

# Words too common to prove two decisions are about the same thing.
STOP_WORDS = {
    "the", "a", "an", "and", "or", "of", "to", "for", "in", "on", "is", "are",
    "be", "we", "our", "this", "that", "it", "at", "by", "with", "from",
}


@dataclass
class Report:
    """What the reader did, and what it could not work out.

    A reader that quietly drops what it does not understand is impossible to
    improve. This is how the rules admit their limits.
    """

    notes_read: int = 0
    facts_added: int = 0
    skipped: list = field(default_factory=list)

    def skip(self, source, bullet, why):
        self.skipped.append({"source": source, "bullet": bullet, "why": why})


def key_words(text):
    """The words in a sentence that carry meaning, lower-cased."""
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {word for word in words if word not in STOP_WORDS and len(word) > 2}


def first_sentence(text):
    """The first sentence of a bullet, without its full stop."""
    sentence = re.split(r"(?<=[.!?])\s+", text.strip())[0]
    return sentence.rstrip(".!?").strip()


def strip_meeting_words(title):
    """"Checkout redesign kickoff" becomes "Checkout redesign"."""
    stripped = title.strip()
    for word in MEETING_WORDS:
        pattern = re.compile(rf"\s*\b{re.escape(word)}\b\s*$", re.IGNORECASE)
        stripped = pattern.sub("", stripped).strip()
    return stripped or title.strip()


def known_people(raw_notes):
    """Every name that appears on an "Attendees:" or "Owner:" line."""
    people = []
    for raw in raw_notes:
        for name in raw.people:
            if name not in people:
                people.append(name)
    return people


def project_names(raw_notes):
    """Guess the project names, from note titles.

    A title becomes a candidate with its meeting words removed. A candidate
    that is contained in a longer one is dropped, so "Checkout" gives way to
    "Checkout redesign": the longer name is the one people actually use.
    """
    candidates = []
    for raw in raw_notes:
        if ONE_ON_ONE.match(raw.title):
            continue
        name = strip_meeting_words(raw.title)
        if name and name not in candidates:
            candidates.append(name)

    kept = []
    for name in candidates:
        longer = [
            other
            for other in candidates
            if other != name and name.lower() in other.lower()
        ]
        if not longer:
            kept.append(name)
    return kept


def find_person(text, people):
    """The known person a sentence is about, matched on full or first name."""
    match = LEADING_NAME.match(text.strip())
    lead = match.group(1) if match else ""
    for name in people:
        if lead and (lead == name or lead == name.split()[0]):
            return name
    return ""


def mentioned_people(text, people):
    """Every known person named anywhere in a sentence."""
    found = []
    for name in people:
        first = name.split()[0]
        if re.search(rf"\b{re.escape(name)}\b", text) or re.search(
            rf"\b{re.escape(first)}\b", text
        ):
            found.append(name)
    return found


def find_project(raw, projects):
    """Which project a raw note is about: the name its text uses most."""
    if not projects:
        return ""
    counts = {
        name: len(re.findall(re.escape(name), raw.text, re.IGNORECASE))
        for name in projects
    }
    best = max(counts, key=lambda name: (counts[name], len(name)))
    if counts[best]:
        return best
    title_project = strip_meeting_words(raw.title)
    return title_project if title_project in projects else ""


class BrainBuilder:
    """Collects notes while reading, so the same person is never written twice."""

    def __init__(self, brain=None):
        self.brain = dict(brain or {})
        self.report = Report()

    def note(self, kind, title):
        """The note for this thing, made if it does not exist yet."""
        note_id = f"{kind}s/{slugify(title)}" if kind != "person" else f"people/{slugify(title)}"
        if note_id not in self.brain:
            self.brain[note_id] = Note(type=kind, title=title)
        return self.brain[note_id]

    def add_fact(self, note, date, text, source, private=False):
        if note.add(Fact(date=date, text=text, source=source, private=private)):
            self.report.facts_added += 1

    def connect(self, first, second):
        if first and second:
            first.link_to(second.id)
            second.link_to(first.id)

    def find_reversed(self, decision_note, project_note):
        """The earlier decision a reversal is most likely to be about.

        Rules cannot read "this reverses the 2026-09-01 decision" and know
        which one. They can compare wording: the earlier decision about the
        same project sharing the most words wins.
        """
        if not project_note:
            return None
        words = key_words(decision_note.title)
        best, best_score = None, 0
        for note_id in project_note.links:
            other = self.brain.get(note_id)
            if not other or other.type != "decision" or other is decision_note:
                continue
            if other.updated > decision_note.updated:
                continue
            score = len(words & key_words(other.title))
            if score > best_score:
                best, best_score = other, score
        return best


def read_note(builder, raw, people, projects):
    """Turn one raw note into facts, people, projects and decisions."""
    date = raw.date
    if not date:
        builder.report.skip(raw.source, raw.title, "no date on the note or its file name")
        return

    one_on_one = ONE_ON_ONE.match(raw.title)
    project_name = find_project(raw, projects)
    project_note = builder.note("project", project_name) if project_name else None

    subject = project_note
    if one_on_one:
        named = find_person(one_on_one.group(2), people) or one_on_one.group(2).strip()
        subject = builder.note("person", named)

    # Everyone in the room knows about the subject, and the subject about them.
    for name in raw.people:
        person = builder.note("person", name)
        if raw.role(name) == "owner":
            summary = f"Owns {subject.title}." if subject else f"Owns: {raw.title}."
        else:
            summary = f"Took part in: {raw.title}."
        builder.add_fact(person, date, summary, raw.source)
        builder.connect(person, subject)
        builder.connect(person, project_note)

    for section, bullet in raw.bullets():
        private = section.is_private
        owner_name = find_person(bullet, people)
        owner = builder.note("person", owner_name) if owner_name else None

        if section.heading.strip().lower().startswith("decision") and not private:
            title = first_sentence(bullet)
            decision = builder.note("decision", title)
            builder.add_fact(decision, date, bullet, raw.source)
            builder.connect(decision, project_note)
            builder.connect(decision, owner)
            for name in mentioned_people(bullet, people):
                builder.connect(decision, builder.note("person", name))

            if any(word in bullet.lower() for word in REVERSAL_WORDS):
                earlier = builder.find_reversed(decision, project_note)
                if earlier:
                    decision.replaces = earlier.id
                    earlier.replaced_by = decision.id
                    builder.connect(decision, earlier)
                else:
                    builder.report.skip(
                        raw.source, bullet, "says it reverses a decision we could not find"
                    )
            continue

        target = owner or subject
        if target is None:
            builder.report.skip(raw.source, bullet, "could not tell who or what it is about")
            continue
        builder.add_fact(target, date, bullet, raw.source, private=private)
        builder.connect(target, subject)
        if not private:
            # A private line must not create a public trail back to the person
            # it is about, so only public bullets add links to those mentioned.
            for name in mentioned_people(bullet, people):
                builder.connect(target, builder.note("person", name))

    builder.report.notes_read += 1


def build(raw_notes, brain=None):
    """Read every raw note into a brain, and report what was skipped."""
    builder = BrainBuilder(brain)
    people = known_people(raw_notes)
    projects = project_names(raw_notes)
    for raw in raw_notes:
        read_note(builder, raw, people, projects)
    return builder.brain, builder.report
