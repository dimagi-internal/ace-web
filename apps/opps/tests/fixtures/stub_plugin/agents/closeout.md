---
name: closeout
description: >
  Orchestrates opportunity closeout: invoice processing, LLO feedback
  collection, learnings summary, and overall cycle grading. Triggered
  when the opportunity reaches its end date.
model: inherit
phase: closeout
phase_display: Closeout
phase_ordinal: 6
skills:
  - { name: opp-closeout,       has_judge: false }
  - { name: llo-feedback,       has_judge: false }
  - { name: learnings-summary,  has_judge: false }
  - { name: cycle-grade,        has_judge: true }
---

# Stub agent (frontmatter only — see apps/opps/tests/conftest.py)
