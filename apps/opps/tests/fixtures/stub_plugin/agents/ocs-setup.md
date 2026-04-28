---
name: ocs-setup
description: >
  Phase 4 of the CRISPR-Connect lifecycle: clone the ACE golden template,
  build the opp-specific RAG collection, quality-gate the bot via quick and
  deep chat suites, and stage the widget credentials for Connect.
model: inherit
phase: ocs-setup
phase_display: OCS Setup
phase_ordinal: 4
skills:
  - { name: ocs-agent-setup,    has_judge: false }
  - { name: ocs-chatbot-qa,     has_judge: false }
  - { name: ocs-chatbot-eval,   has_judge: true }
---

# Stub agent (frontmatter only — see apps/opps/tests/conftest.py)
