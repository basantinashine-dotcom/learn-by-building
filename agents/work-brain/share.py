"""Writing something you can post to the team.

Answering a question is for you. Sharing is different: what comes out is read
by other people, and some of what the brain knows is nobody else's business.

The guard has two layers, and the reason for two is worth saying plainly.

**Layer one: the model never sees a private fact.** ``public_brain`` makes a
copy of the brain with private facts stripped out, and the copy is what the
summary is written from. Nothing can leak out of a room the model was never in.

**Layer two: the draft is checked against the private facts anyway.** A private
fact can reach the model by another road, for instance if the same thing was
also said in a public part of another note, or if a future version of this file
passes the wrong brain in. So ``find_leaks`` compares the finished draft against
every private fact the real brain holds, and any sentence that echoes one is
cut before you see the draft.

Layer one is the design. Layer two is what catches the day layer one is broken
by accident, which is the day that actually matters. Neither layer is a prompt:
a rule the model is asked to follow is a rule that holds most of the time, and
"most of the time" is not a privacy guarantee.

**What this check cannot do.** Layer two compares words. It catches a copy and
it catches a light rewording, because "moving" and "move" are stemmed to the
same thing. It does not catch a real paraphrase: "Marcus may not be around for
long" shares no words with anything private and sails through. There is a test
for that, ``test_a_full_paraphrase_is_not_caught``, so the gap is written down
rather than hoped away. Closing it would mean asking a model whether a draft
gives away a secret, which means showing the secret to the model, which is the
thing layer one exists to avoid. Layer one is the guarantee. Layer two is a
backstop, and a backstop that catches most of what gets past a wall is worth
having as long as nobody mistakes it for the wall.
"""

import re
from dataclasses import replace

from brain import Note

MODEL = "claude-opus-5"
MAX_TOKENS = 1500

# How much of a private fact's distinctive wording has to turn up in a sentence
# before we call it a leak. Low on purpose: cutting an innocent sentence costs
# you a line of a summary, letting one through costs someone's trust.
LEAK_RATIO = 0.5
LEAK_MIN_WORDS = 2

STOP_WORDS = {
    "the", "a", "an", "and", "or", "of", "to", "for", "in", "on", "is", "are",
    "was", "were", "be", "been", "we", "our", "us", "this", "that", "it", "at",
    "by", "with", "from", "his", "her", "they", "them", "has", "have", "had",
    "will", "would", "next", "last", "about", "into", "out", "up", "off",
}

SYSTEM = """You write a short update that a team will read.

You are given facts from one person's work brain, each with a date and the note \
it came from. Write what the team needs to know.

Rules:
- Use only the facts you are given. Never add context you were not told.
- Lead with what changed and what it means for the work.
- Say who owns what, and name dates that people need to plan around.
- Plain sentences. No headings, no filler, no "I hope this finds you well".
- If a decision was overturned, say what holds now; mention the old one only if \
it helps the reader.
- Six sentences at most. Shorter is better."""


def public_brain(brain):
    """A copy of the brain with every private fact removed.

    The notes are copied rather than edited, because the caller still needs the
    real brain: layer two checks the draft against the private facts.
    """
    public = {}
    for note_id, note in brain.items():
        public[note_id] = Note(
            type=note.type,
            title=note.title,
            facts=[replace(fact) for fact in note.public_facts()],
            links=list(note.links),
            replaces=note.replaces,
            replaced_by=note.replaced_by,
        )
    return public


def private_facts(brain):
    """Every private fact in the brain, whichever note it sits in."""
    return [fact for note in brain.values() for fact in note.facts if fact.private]


def stem(word):
    """Cut a common ending so "moving" and "move" count as the same word.

    Crude on purpose. A real stemmer would be better, and would still not
    catch a proper paraphrase: see "What this check cannot do" below.
    """
    for ending in ("ing", "ed", "es", "s"):
        if len(word) > len(ending) + 2 and word.endswith(ending):
            word = word[: -len(ending)]
            break
    # "moving" becomes "mov" above while "move" stays whole, so drop a trailing
    # e from both and the two forms finally meet.
    return word[:-1] if len(word) > 3 and word.endswith("e") else word


def key_words(text):
    """The distinctive words of a sentence, lower-cased and stemmed."""
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {stem(word) for word in words if word not in STOP_WORDS and len(word) > 2}


def split_sentences(text):
    """Break a draft into sentences, keeping bullet lines whole."""
    pieces = []
    for line in (text or "").splitlines():
        if not line.strip():
            continue
        if line.strip().startswith(("-", "*")):
            pieces.append(line.strip())
            continue
        pieces += [part.strip() for part in re.split(r"(?<=[.!?])\s+", line) if part.strip()]
    return pieces


def leaks(sentence, secrets):
    """The private facts a sentence gives away, if any."""
    said = key_words(sentence)
    found = []
    for fact in secrets:
        wanted = key_words(fact.text)
        if not wanted:
            continue
        shared = wanted & said
        if len(shared) >= LEAK_MIN_WORDS and len(shared) / len(wanted) >= LEAK_RATIO:
            found.append(fact)
    return found


def find_leaks(text, brain):
    """Every (sentence, private fact) pair the draft gives away."""
    secrets = private_facts(brain)
    return [
        {"sentence": sentence, "fact": fact.text, "source": fact.source}
        for sentence in split_sentences(text)
        for fact in leaks(sentence, secrets)
    ]


def redact(text, brain):
    """Cut any sentence that echoes a private fact. Returns text and what went."""
    secrets = private_facts(brain)
    kept, removed = [], []
    for sentence in split_sentences(text):
        found = leaks(sentence, secrets)
        if found:
            removed.append({"sentence": sentence, "fact": found[0].text})
        else:
            kept.append(sentence)
    return " ".join(kept), removed


def gather(brain, topic, limit=25):
    """The public facts worth putting in a summary about ``topic``.

    Facts come back newest first: an update is about what changed, and an old
    fact only earns its place when nothing newer fills the space.
    """
    from ask import expand, search  # imported here to keep the modules independent

    public = public_brain(brain)
    notes = search(public, topic, limit=6, include_private=False)
    rows = []
    for note in expand(public, notes):
        for fact in note.facts:
            rows.append((fact.date, note, fact))
    rows.sort(key=lambda row: row[0], reverse=True)
    return rows[:limit]


def render_facts(rows):
    """The gathered facts as text for the model."""
    lines = []
    for date, note, fact in rows:
        state = " [no longer holds]" if note.replaced_by else ""
        lines.append(f"- {date} | {note.title}{state} | {fact.text} | from {fact.source}")
    return "\n".join(lines)


def offline_summary(rows, topic):
    """A summary with no model: the facts themselves, newest first."""
    if not rows:
        return f"The brain has nothing public about {topic!r}."
    lines = [f"Update on {topic} (offline mode lists facts, it does not write prose):"]
    for date, note, fact in rows:
        state = " (no longer holds)" if note.replaced_by else ""
        lines.append(f"- {date} — {note.title}{state}: {fact.text}")
    return "\n".join(lines)


def summarise(brain, topic, client=None):
    """Write something postable about ``topic``.

    With a client, Claude writes it from public facts only. Without one, you
    get the facts themselves. Either way the draft is checked against the real
    brain's private facts before it is returned.

    Returns the text, the facts it was built from, and anything that was cut.
    """
    rows = gather(brain, topic)
    if not rows:
        return {
            "text": f"Nothing to share about {topic}: the brain has no public facts on it.",
            "used": [],
            "removed": [],
            "mode": "empty",
        }

    if client is None:
        text, removed = redact(offline_summary(rows, topic), brain)
        mode = "offline"
    else:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM,
            messages=[{
                "role": "user",
                "content": f"Write an update about: {topic}\n\nFacts:\n{render_facts(rows)}",
            }],
        )
        draft = " ".join(
            block.text for block in response.content
            if getattr(block, "type", "") == "text"
        ).strip()
        text, removed = redact(draft, brain)
        mode = "live"

    return {
        "text": text or "Everything in the draft had to be cut. Nothing safe to share.",
        "used": [
            {"date": date, "note": note.id, "fact": fact.text, "source": fact.source}
            for date, note, fact in rows
        ],
        "removed": removed,
        "mode": mode,
    }
