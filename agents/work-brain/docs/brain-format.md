# What a memory note looks like

Work Brain reads your raw notes and writes a **brain**: a folder of small
Markdown files, one per thing worth remembering. This page explains the shape of
those files and why they are shaped that way.

## One note per thing

A thing is a person, a project or a decision. Each gets its own file:

```text
brain/
├── people/
│   ├── priya-shah.md
│   └── marcus-lee.md
├── projects/
│   ├── checkout-redesign.md
│   └── weekly-deals-email.md
└── decisions/
    ├── remove-guest-checkout.md
    └── keep-guest-checkout.md
```

The file name is the thing's name in lower case with dashes, so the same name
always lands in the same file. Read a note again tomorrow and it is the same
note, not a second copy.

## The shape of a note

```markdown
---
type: decision
title: Keep guest checkout
updated: 2026-09-08
links: projects/checkout-redesign, people/priya-shah
replaces: decisions/remove-guest-checkout
---

## Facts

- 2026-09-08 | Guest checkout stays: 41% of first-time buyers use it. | source: 2026-09-08-checkout-design-review.md
- 2026-09-08 | Guests are offered "Save your details" after paying. | source: 2026-09-08-checkout-design-review.md
```

The part between the `---` lines is the **header**: a few labelled lines that
describe the note as a whole.

| Header field | What it is |
| --- | --- |
| `type` | `person`, `project` or `decision`. It decides which folder the note lives in. |
| `title` | The thing's name, written the way a person would say it. |
| `updated` | The date of the newest fact in the note. |
| `links` | Other notes this one is connected to. |
| `replaces` | For a decision that overturns an earlier one. |
| `replaced_by` | Written on the older decision, pointing at the newer one. |

Everything under `## Facts` is the **body**: one line per fact.

## The shape of a fact

```text
- 2026-09-12 | Marcus may move to the Search team next quarter. | source: 2026-09-12-one-on-one-marcus.md | private
```

Four parts, separated by `|`:

1. **When** it was true, as a date. Not when it was written down: when it
   happened, as best the note says.
2. **What** happened, in one sentence a person can read.
3. **Where it came from**: the raw note this was taken from.
4. **`private`**, if the fact came from a private part of a note. Most facts do
   not have this, so most lines have three parts.

## Why this shape

**Why Markdown files instead of a database?** You can open the brain in any text
editor and read it. If the brain gets something wrong, you fix the line yourself.
Nothing is trapped in a format only this program understands.

**Why a source on every fact?** So an answer can show its work: "Guest checkout
stays, from the Sept 8 design review." Without the source you have to trust the
program. With it, you can check. This is the main defence against an AI that
sounds confident and is wrong.

**Why a date on every fact?** Because work changes its mind. The team removed
guest checkout on Sept 1 and brought it back on Sept 8. Both are true, and the
newer one wins. A brain that keeps only the latest fact cannot explain how the
team got there; a brain that keeps both, in order, can.

**Why `replaces` and `replaced_by`?** A reversed decision is not a mistake to
delete, it is history. Keeping the old note with a pointer to the new one means
"Why did we change our mind about guest checkout?" has an answer.

**Why mark private facts instead of dropping them?** Because they are useful to
you. If Marcus is stressed by the old payment code, that matters when you plan
his next month. It just must not leak into anything the team sees. Marking it
lets one brain serve both jobs, and the mark is checked in one place in the
code rather than remembered by hand every time.

## The rule that makes this work

**A fact never appears without its source.** If Work Brain cannot say where a
fact came from, the fact does not go in the brain. That rule is what turns a
pile of notes into memory you can trust.
