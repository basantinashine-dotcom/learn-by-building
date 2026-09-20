# Decision Log

**Six months from now someone will ask why you built it this way, and nobody
will remember.**

The decision is in a meeting note somewhere. The reason is in a different note,
argued three bullets before anyone wrote down what was agreed. The person who
made the call has moved teams. So the team relitigates a question it already
settled, or worse, quietly reverses a decision without ever learning why it was
made.

Decision Log reads your meeting notes and keeps every decision together with
**the reason it was made**, what it overturned, who owns it, and the note each
fact came from. Then you can ask it why, or have it explain a decision to the
team with anything private held back.

![The Decision Log page: a timeline of decisions on the left, each with its
status and reason, and a panel on the right showing why "Keep guest checkout"
was decided, what it replaced, and the note every fact came from](docs/screenshot-log.png)

*The sample notes produce ten decisions: two later reversed, and four where
nobody wrote down why. That last number is the point. A gap you can see is a gap
you can fix in your next meeting.*

## Try it

From this folder, with Python 3.10 or later and no dependencies to install:

```sh
python web.py
```

A browser tab opens at http://127.0.0.1:8766. Press **Read the notes**, then ask
it *"why do we have guest checkout?"*

That is offline mode: rules only, no API key, nothing leaves your machine. To
have Claude read the notes instead, `pip install -r requirements.txt`, set
`ANTHROPIC_API_KEY` in the same terminal, restart, and tick **Live mode**.

Point it at your own notes with `python web.py --notes path/to/your/notes`.

## What you get

Ask it a question and the answer comes with its evidence. This is offline mode,
which shows you the record rather than writing prose:

```text
Keep guest checkout — still holds, decided 2026-09-08
  why: Priya shared the data: 41% of first-time buyers use guest checkout.
       Forcing them to sign in would likely make abandonment worse, not better.
       [2026-09-08-checkout-design-review.md]
  replaced: Remove guest checkout (2026-09-01)

Remove guest checkout — no longer holds, decided 2026-09-01
  why: Priya thinks guest checkout creates duplicate accounts and messy order
       history. [2026-09-01-checkout-kickoff.md]
```

Live mode turns the same evidence into a few sentences, and records which notes
it searched, opened and cited so you can check it against them.

Ask for a decision to be explained to the team and you get something postable,
with private facts held back and anything cut reported to you.

## Will this work on my notes?

It reads plain Markdown files from one folder. It gets more out of a note that
has these, and none of them are unusual in a meeting note:

| In your note | Why it helps |
| --- | --- |
| A date: `2026-09-08-review.md` or a `Date: 2026-09-08` line | Everything is ordered by when it happened, and a fact with no date cannot be filed. |
| `Attendees:` or `Owner:` line | This is how people are found, and how a decision gets an owner. |
| A `## Decisions` heading | Offline mode looks for it by name. Live mode does not need it. |
| The word "because" | Both readers take what follows as the reason. |
| `## Private` | Everything under it is marked private and kept out of anything you share. |

Bullets can wrap over several lines. Anything the reader cannot place is listed
back to you rather than dropped silently.

Offline mode is literal: rename `## Decisions` to `## What we agreed` and it
stops finding decisions. Live mode copes, and the difference between the two on
your own notes is the most interesting thing you can learn here.

## What it does with a note

Give it a meeting note like this one:

```markdown
# Checkout design review

Date: 2026-09-08
Attendees: Priya Shah, Marcus Lee, Ana Ruiz

## Discussion

- Priya shared the data: 41% of first-time buyers use guest checkout. Forcing
  them to sign in would likely make abandonment worse, not better.

## Decisions

- Keep guest checkout. This reverses the 2026-09-01 decision.
```

and it writes this:

```markdown
---
type: decision
title: Keep guest checkout
status: current
updated: 2026-09-08
owner: people/priya-shah
project: projects/checkout-redesign
replaces: decisions/remove-guest-checkout
---

## Why

- 2026-09-08 | 41% of first-time buyers use guest checkout, so forcing sign-in would make abandonment worse. | source: 2026-09-08-checkout-design-review.md | why
```

The earlier decision is not deleted. It is marked `reversed`, keeps the reason
the team believed it at the time, and points at the decision that replaced it.
That chain is what answers "why did we change our minds?"

The full format is in [docs/log-format.md](docs/log-format.md).

## The four ideas worth stealing

**1. No quote, no fact.** Claude must return a sentence copied out of your note
for every fact it proposes. The code checks that the sentence is really there,
word for word, and throws the fact away if it is not. It is a dumb string
search, and that is the point: the model cannot talk its way past it. It cannot
stop a misreading of a real sentence, but it stops an event nobody wrote down,
which is the failure that actually burns people.

**2. Rules first, model second.** `offline.py` builds the same log with nothing
but pattern matching: headings, names, dates, a "because" clause. It exists so
anyone can run this for free, so the tests are fast and predictable, and so the
model has something to beat. If the rules already do the job, the model is not
earning its place.

**3. Privacy is enforced in code, not asked for in a prompt.** Anything under a
`## Private` heading is marked private when it is read. When you share a
decision, the draft is written from a copy of the log with private facts
stripped out, so the model never sees them. The finished draft is then checked
against the real log anyway and any sentence echoing a private fact is cut. Two
layers, because the first one is the guarantee and the second is what catches
the day the first is broken by accident.

**4. Show the work.** Every answer records which notes it searched, opened and
cited, and every fact on screen links to the note it came from. The page also
shows what the reader **could not** place, and how many decisions have no
recorded reason.

## What you can learn here

This is a learning project, not a product. If you are studying how AI features
are actually built, it is a worked example of four things:

- **How AI memory works**: turning messy notes into structured, linked facts,
  and what has to be stored for an answer to be checkable later.
- **How to keep a model honest**: the quote check, and what it can and cannot
  catch.
- **Retrieval as tools**: the model searches and opens notes itself rather than
  being handed the whole log, and leaves a trail either way.
- **Privacy as a product decision**: what is allowed to cross from private to
  shared, and why that belongs in code.

**Read the code in this order.** Each file is short and says why it exists at
the top:

1. [`notes.py`](notes.py) — reading a raw Markdown note into its pieces
2. [`brain.py`](brain.py) — the note format, and the only file that knows it
3. [`offline.py`](offline.py) — the rules-only reader, the baseline
4. [`live.py`](live.py) — Claude, behind the quote check
5. [`ask.py`](ask.py) — search, and the tool loop that answers questions
6. [`share.py`](share.py) — explaining one decision, behind both privacy layers
7. [`web.py`](web.py) — the local server, which holds the API key

## What it does not do

- **It reads a folder, not your inbox.** No email, calendar or chat connectors.
- **It is single-player.** There is no shared server and no team view.
- **`## Private` is a convention you have to keep.** It only protects what you
  mark.
- **The leak check compares words.** It catches a copy or a light rewording. A
  full paraphrase gets past it, and there is a test that says so. The first
  layer is what keeps the secret out of the draft.
- **Live mode costs money per note**, and rereads every note when you rebuild.

## Tests

```sh
python -m unittest discover -s tests -t .
```

The whole suite runs with no API key and no network: the Claude paths are driven
by a fake client that replays canned answers, including a model that invents a
quote and a model that leaks a private fact.

The server listens on 127.0.0.1 only, checks the `Host` header, requires JSON on
every POST, and never takes a file path from the browser. There are tests for
each of those.

## Where it came from

The idea is borrowed from [Rowboat](https://github.com/rowboatlabs/rowboat), an
open-source AI coworker that keeps a long-lived memory of your work as plain
Markdown and makes sharing explicit. This is a much smaller thing, built from
scratch to learn how that kind of memory works: no code was copied.
