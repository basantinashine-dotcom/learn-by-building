# What a note in the log looks like

The Decision Log reads your raw notes and writes a folder of small Markdown
files, one per thing worth remembering. This page explains the shape of those
files and why they are shaped that way.

## One note per thing

The log is about **decisions**. People and projects exist to give a decision an
owner and a home.

```text
log/
├── decisions/
│   ├── keep-guest-checkout.md
│   └── remove-guest-checkout.md
├── people/
│   ├── priya-shah.md
│   └── marcus-lee.md
└── projects/
    └── checkout-redesign.md
```

The file name is the title in lower case with dashes, cut short if the title is
a whole sentence. The same name always lands in the same file, so reading a
note again tomorrow updates it instead of making a second copy.

## The shape of a decision

```markdown
---
type: decision
title: Keep guest checkout
status: current
updated: 2026-09-08
owner: people/priya-shah
project: projects/checkout-redesign
links: projects/checkout-redesign, decisions/remove-guest-checkout
replaces: decisions/remove-guest-checkout
---

## Why

- 2026-09-08 | 41% of first-time buyers use guest checkout, so forcing sign-in would make abandonment worse. | source: 2026-09-08-checkout-design-review.md | why

## Facts

- 2026-09-08 | Guests are offered "Save your details" after paying. | source: 2026-09-08-checkout-design-review.md
```

The part between the `---` lines is the **header**.

| Header field | What it is |
| --- | --- |
| `type` | `decision`, `person` or `project`. It decides which folder the note lives in. |
| `title` | The decision as the team would say it. |
| `status` | `current` or `reversed`. Worked out from `replaced_by`, never stored by hand. |
| `updated` | The date of the newest fact in the note. |
| `owner` | The person who owns the decision. |
| `project` | The project it belongs to. |
| `links` | Other notes this one touches. |
| `replaces` | The decision this one overturned. |
| `replaced_by` | Written on the older decision, pointing at the newer one. |

Then two sections. **Why** holds the reasons. **Facts** holds everything else.

## The shape of a fact

```text
- 2026-09-12 | Marcus may move to the Search team next quarter. | source: 2026-09-12-one-on-one-marcus.md | private
```

Up to five parts, separated by `|`:

1. **When** it was true, as a date. Not when it was written down.
2. **What** happened, in one sentence someone could read a year from now.
3. **Where it came from**: the raw note it was taken from.
4. **`why`**, if this is a reason the decision was made rather than background.
5. **`private`**, if it came from a private part of a note.

## Why this shape

**Why is the reason a separate thing?** Because it is the question the whole
log exists to answer. A log that records *"Keep guest checkout"* and not
*"because 41% of first-time buyers use it"* tells you what happened and leaves
you no wiser. Keeping reasons apart from background means the page can lead
with them, and it makes a missing reason visible instead of invisible: a
decision with no `why` is shown as a gap, not quietly padded with other facts.

**Why a source on every fact?** So an answer can show its work: "from the Sept 8
design review." Without the source you have to trust the program. With it, you
can check. This is the main defence against an AI that sounds confident and is
wrong.

**Why a date on every fact?** Because work changes its mind. The team removed
guest checkout on Sept 1 and brought it back on Sept 8. Both are true, and the
newer one wins.

**Why `replaces` and `replaced_by`?** A reversed decision is not a mistake to
delete, it is the most interesting thing in the log. Keeping the old note, with
its own reason, is what lets the log answer "why did we change our minds?"

**Why mark private facts instead of dropping them?** Because they are useful to
you. If Marcus is stressed by the old payment code, that matters when you plan
his next month. It just must never leak into anything the team sees. Marking it
lets one log serve both jobs, and the mark is checked in one place in the code
rather than remembered by hand every time.

**Why Markdown files instead of a database?** You can open the log in any text
editor and read it. If it gets something wrong, you fix the line yourself.
Nothing is trapped in a format only this program understands.

## The rule that makes this work

**A fact never appears without its source.** If the reader cannot say where a
fact came from, the fact does not go in the log. That rule is what turns a pile
of notes into a record you can defend in a meeting.
