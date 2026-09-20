"""Reading the raw notes you drop into a folder.

This module knows nothing about the brain. It only turns a Markdown file into
the pieces every reader needs: when it happened, what it is called, who was
there, and the bullets under each heading.

Both readers use it: the rule-based one in ``offline.py`` and the Claude one in
``live.py``. Keeping the raw parsing here means the two readers see exactly the
same input, so a difference in their output is a difference in reading, not in
file handling.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

# A file named 2026-09-01-checkout-kickoff.md happened on 2026-09-01.
FILENAME_DATE = re.compile(r"^(\d{4}-\d{2}-\d{2})")

# A "Date: 2026-09-01" line inside the note beats the file name.
DATE_LINE = re.compile(r"^date\s*:\s*(\d{4}-\d{2}-\d{2})", re.IGNORECASE)

# "Attendees: Priya Shah, Marcus Lee" and "Owner: Jordan Kim".
PEOPLE_LINE = re.compile(r"^(attendees|owner|present|people)\s*:\s*(.+)", re.IGNORECASE)

BULLET = re.compile(r"^\s*[-*]\s+(.*)")
HEADING = re.compile(r"^(#{1,6})\s+(.*)")

# A bullet wrapped over several lines is still one bullet. Without this, a
# sentence is cut in half at the margin and the half holding the number, the
# date or the reason is thrown away.
CONTINUATION = re.compile(r"^\s{2,}(\S.*)")

# Headings whose bullets are nobody else's business.
PRIVATE_HEADINGS = ("private", "confidential", "personal")


@dataclass
class Section:
    """One heading in a raw note and the bullets under it."""

    heading: str
    bullets: list = field(default_factory=list)

    @property
    def is_private(self):
        return self.heading.strip().lower() in PRIVATE_HEADINGS


@dataclass
class RawNote:
    """One file you dropped into the notes folder."""

    source: str
    title: str
    date: str
    people: list = field(default_factory=list)
    roles: dict = field(default_factory=dict)
    sections: list = field(default_factory=list)
    text: str = ""

    def role(self, name):
        """How this person appears on the note: ``owner`` or ``attendee``."""
        return self.roles.get(name, "attendee")

    def section(self, heading):
        """The section with this heading, or None."""
        for section in self.sections:
            if section.heading.strip().lower() == heading.strip().lower():
                return section
        return None

    def bullets(self, private=None):
        """Every (section, bullet) pair, optionally filtered by privacy."""
        return [
            (section, bullet)
            for section in self.sections
            for bullet in section.bullets
            if private is None or section.is_private == private
        ]


def split_people(value):
    """Turn "Priya Shah, Marcus Lee and Ana Ruiz" into three names."""
    names = []
    for part in re.split(r",| and ", value):
        name = part.strip().strip(".")
        if name and name.lower() not in ("me", "myself"):
            names.append(name)
    return names


def parse_raw_note(path):
    """Read one Markdown file into a ``RawNote``."""
    path = Path(path)
    text = path.read_text(encoding="utf-8")

    match = FILENAME_DATE.match(path.name)
    date = match.group(1) if match else ""
    title = ""
    people = []
    roles = {}
    sections = []
    current = None

    for line in text.splitlines():
        heading = HEADING.match(line)
        if heading:
            level, name = len(heading.group(1)), heading.group(2).strip()
            if level == 1 and not title:
                # The first "# Heading" is the note's own title, not a section.
                title = name
            else:
                current = Section(heading=name)
                sections.append(current)
            continue

        date_line = DATE_LINE.match(line.strip())
        if date_line:
            date = date_line.group(1)
            continue

        people_line = PEOPLE_LINE.match(line.strip())
        if people_line:
            label = people_line.group(1).lower()
            for name in split_people(people_line.group(2)):
                if name not in people:
                    people.append(name)
                roles.setdefault(name, "owner" if label == "owner" else "attendee")
            continue

        bullet = BULLET.match(line)
        if bullet and current and bullet.group(1).strip():
            current.bullets.append(bullet.group(1).strip())
            continue

        wrapped = CONTINUATION.match(line)
        if wrapped and current and current.bullets:
            current.bullets[-1] += " " + wrapped.group(1).strip()

    return RawNote(
        source=path.name,
        title=title or path.stem,
        date=date,
        people=people,
        roles=roles,
        sections=sections,
        text=text,
    )


def load_raw_notes(folder):
    """Read every Markdown file in a folder, oldest first.

    Notes are sorted by date because later notes can overturn earlier ones, and
    a reader that sees them out of order would get the story backwards.
    """
    folder = Path(folder)
    if not folder.is_dir():
        return []
    notes = [parse_raw_note(path) for path in sorted(folder.glob("*.md"))]
    return sorted(notes, key=lambda note: (note.date, note.source))
