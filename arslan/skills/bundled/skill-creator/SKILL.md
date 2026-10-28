---
name: skill-creator
description: Skill creator — package a reusable method or workflow into a high-quality, persona-independent SKILL.md that any persona can reuse, and refine it over iterations. Use when the user says "turn this workflow into a skill" or "improve this skill".
version: 0.2.0
authors:
  - Arslan
source: adapted from anthropics/skills · skill-creator (Apache-2.0); Claude-Code-specific eval tooling removed
---

> Adapted from Anthropic's skill-creator (Apache-2.0), github.com/anthropics/skills @ dbd4588f, skills/skill-creator. Changed: shortened and translated; Claude-Code-specific eval tooling (claude -p, subagents, eval viewer, scripts) removed.

## Trigger

Activate when the user wants to turn a method they "do the same way every time" into a reusable skill — creating a new skill, improving or optimizing an existing one, or giving a persona a new cross-cutting capability. The output is a well-structured `SKILL.md` (techniques and rules, not a one-off answer) that any persona can be equipped with.

## Decision Rules

- **Decide "when to use it" first (Trigger):** a good skill first says clearly in which situations it should activate — concretely and checkably; put the trigger conditions in the `description` too, because that decides whether the skill gets called at the right time.
- **A skill is decision rules, not a long tutorial:** the main body is a set of "when X, do Y" judgment rules (6 or more is a good target), each able to guide behaviour on its own; no encyclopedic background and no one-off content.
- **Persona-independent and reusable:** a skill is a cross-cutting capability (any persona can be equipped with it), not tied to a particular persona or task; keep "who does it" separate from "how it is done".
- **Draft → actually run a few examples → revise from the results:** do not finalize after one pass; take 3 representative scenarios, have a persona equipped with the skill actually run them, check whether it followed the rules, then tighten the rules where it did not.
- **Format:** the frontmatter has `name` (lowercase, hyphenated) and `description` (one sentence on what it does plus when to use it); the body has `## Trigger` and `## Decision Rules`; keep it short enough to read aloud and act on.
- **Honest limits, no hallucination:** any skill that touches external data or execution must say in its rules "when unsure, verify or escalate; never invent"; do not write capabilities into it that the skill does not have.
- **Iterate:** a skill is not finished in one go; after it ships, keep tightening the rules from real usage feedback (this is also what Arslan's evolution layer can optimize automatically).

## Made by the user or by Arslan

The user can say "turn <some workflow> into a skill", and you produce a `SKILL.md` by the rules above and save it to the skill library for yourself or a persona to reuse — so the library holds not only third-party skills but **third-party plus self-made** ones.
