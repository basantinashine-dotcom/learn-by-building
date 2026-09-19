"""The brain: small Markdown notes about people, projects and decisions.

This module is the only place that knows how a note is written to disk. Every
other part of Work Brain works with ``Note`` and ``Fact`` objects and never
parses Markdown itself, so the file format can change in one place.

The format is described for humans in ``docs/brain-format.md``. In short, a
note is a header between ``---`` lines followed by one fact per line:

    ---
    type: decision
    title: Keep guest checkout
    updated: 2026-09-08
    links: projects/checkout-redesign
    ---

    ## Facts

    - 2026-09-08 | Guest checkout stays. | source: 2026-09-08-review.md

Anything the parser does not recognise is skipped rather than raising, because
the brain is meant to be edited by hand and a stray blank line or comment
should never stop the program from reading the rest.
"""

import re
import unicodedata
from dataclasses import dataclass, field, replace
from pathlib import Path

# A note's type decides its folder. Keeping the mapping here means a new type
# only has to be added in one place.
FOLDERS = {"person": "people", "project": "projects", "decision": "decisions"}

# Header fields that hold a list of note ids rather than a single value.
LIST_FIELDS = ("links",)

FACT_SEPARATOR = "|"
SOURCE_PREFIX = "source:"
PRIVATE_MARK = "private"
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class BrainError(ValueError):
    """Raised when a note cannot be built or read."""


@dataclass(frozen=True)
class Fact:
    """One thing the brain remembers, and where it learned it.

    ``date`` is when the fact was true (usually the date of the note it came
    from), not when it was written to the brain.
    """

    date: str
    text: str
    source: str
    private: bool = False

    def __post_init__(self):
        if not DATE_PATTERN.match(self.date):
            raise BrainError(f"fact date must look like 2026-09-01, got {self.date!r}")
        if not self.text.strip():
            raise BrainError("a fact needs text")
        if not self.source.strip():
            raise BrainError(f"a fact needs a source: {self.text!r}")
        if FACT_SEPARATOR in self.text:
            # The separator is what splits a line back into its parts, so it
            # cannot appear inside one.
            object.__setattr__(self, "text", self.text.replace(FACT_SEPARATOR, "/"))

    def render(self):
        """Write the fact as one Markdown list line."""
        parts = [self.date, self.text.strip(), f"{SOURCE_PREFIX} {self.source}"]
        if self.private:
            parts.append(PRIVATE_MARK)
        return "- " + f" {FACT_SEPARATOR} ".join(parts)


@dataclass
class Note:
    """One thing worth remembering, with every fact the brain has about it."""

    type: str
    title: str
    facts: list = field(default_factory=list)
    links: list = field(default_factory=list)
    replaces: str = ""
    replaced_by: str = ""

    def __post_init__(self):
        if self.type not in FOLDERS:
            raise BrainError(
                f"unknown note type {self.type!r}; expected one of {', '.join(FOLDERS)}"
            )
        if not self.title.strip():
            raise BrainError("a note needs a title")

    @property
    def slug(self):
        """The file name, without the folder or the ``.md``."""
        return slugify(self.title)

    @property
    def id(self):
        """How other notes refer to this one, e.g. ``people/marcus-lee``."""
        return f"{FOLDERS[self.type]}/{self.slug}"

    @property
    def updated(self):
        """The date of the newest fact, or empty for a note with no facts."""
        return max((fact.date for fact in self.facts), default="")

    def public_facts(self):
        """Every fact that is safe to share outside your own machine."""
        return [fact for fact in self.facts if not fact.private]

    def add(self, fact):
        """Add a fact unless the note already has it.

        Re-reading the same raw note should not double every line, so a fact
        that matches an existing one on date, text and source is dropped.
        """
        for existing in self.facts:
            if (existing.date, existing.text, existing.source) == (
                fact.date,
                fact.text,
                fact.source,
            ):
                if fact.private and not existing.private:
                    # If the same sentence turns up in a private section, the
                    # careful reading wins.
                    self.facts[self.facts.index(existing)] = replace(
                        existing, private=True
                    )
                return False
        self.facts.append(fact)
        self.facts.sort(key=lambda item: (item.date, item.text))
        return True

    def link_to(self, note_id):
        """Connect this note to another one, at most once."""
        if note_id and note_id != self.id and note_id not in self.links:
            self.links.append(note_id)
            self.links.sort()
            return True
        return False

    def render(self):
        """Write the whole note as Markdown."""
        header = {
            "type": self.type,
            "title": self.title,
            "updated": self.updated,
            "links": ", ".join(self.links),
            "replaces": self.replaces,
            "replaced_by": self.replaced_by,
        }
        lines = ["---"]
        lines += [f"{key}: {value}" for key, value in header.items() if value]
        lines += ["---", "", "## Facts", ""]
        lines += [fact.render() for fact in self.facts]
        return "\n".join(lines) + "\n"


def slugify(title):
    """Turn a title into a file name: ``Marcus Lee`` becomes ``marcus-lee``.

    Accents are folded to plain letters so the same name cannot end up in two
    files, one with an accent and one without.
    """
    plain = unicodedata.normalize("NFKD", title)
    plain = plain.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")
    if not slug:
        raise BrainError(f"cannot make a file name from {title!r}")
    return slug


def parse_fact(line):
    """Read one ``- date | text | source: file`` line, or return None."""
    if not line.strip().startswith("-"):
        return None
    parts = [part.strip() for part in line.strip()[1:].split(FACT_SEPARATOR)]
    if len(parts) < 3 or not DATE_PATTERN.match(parts[0]):
        return None
    source = ""
    private = False
    for part in parts[2:]:
        if part.lower() == PRIVATE_MARK:
            private = True
        elif part.lower().startswith(SOURCE_PREFIX):
            source = part[len(SOURCE_PREFIX) :].strip()
    if not source:
        return None
    try:
        return Fact(date=parts[0], text=parts[1], source=source, private=private)
    except BrainError:
        return None


def parse_note(text):
    """Read a whole note back into a ``Note``."""
    lines = text.splitlines()
    header = {}
    body_start = 0
    if lines and lines[0].strip() == "---":
        for index, line in enumerate(lines[1:], start=1):
            if line.strip() == "---":
                body_start = index + 1
                break
            key, separator, value = line.partition(":")
            if separator:
                header[key.strip().lower()] = value.strip()
        else:
            raise BrainError("the header is missing its closing ---")
    if "type" not in header or "title" not in header:
        raise BrainError("a note needs a type and a title in its header")

    links = [item.strip() for item in header.get("links", "").split(",") if item.strip()]
    note = Note(
        type=header["type"],
        title=header["title"],
        links=links,
        replaces=header.get("replaces", ""),
        replaced_by=header.get("replaced_by", ""),
    )
    for line in lines[body_start:]:
        fact = parse_fact(line)
        if fact:
            note.add(fact)
    return note


def note_path(root, note):
    """Where a note belongs inside the brain folder."""
    return Path(root) / FOLDERS[note.type] / f"{note.slug}.md"


def save_note(root, note):
    """Write one note to disk, creating its folder if needed."""
    path = note_path(root, note)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(note.render(), encoding="utf-8")
    return path


def load_note(path):
    """Read one note from disk."""
    path = Path(path)
    try:
        return parse_note(path.read_text(encoding="utf-8"))
    except BrainError as error:
        raise BrainError(f"{path.name}: {error}") from error


def load_brain(root):
    """Read every note in a brain folder, keyed by note id.

    A missing folder gives an empty brain rather than an error: that is simply
    a brain nobody has built yet.
    """
    root = Path(root)
    brain = {}
    for folder in FOLDERS.values():
        for path in sorted((root / folder).glob("*.md")):
            note = load_note(path)
            brain[note.id] = note
    return brain


def save_brain(root, brain):
    """Write every note in ``brain`` to disk."""
    return [save_note(root, note) for note in brain.values()]
