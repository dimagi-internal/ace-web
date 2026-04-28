---
name: llo-manager
description: >
  Phase 5 of the CRISPR-Connect lifecycle: first LLO contact through go-live
  and ongoing monitoring. Prepares the LLO invite list, sends Connect invites
  and the ACE onboarding email (with OCS widget link), runs UAT, activates
  the opportunity, and keeps recurring monitoring skills running.
model: inherit
phase: llo-management
phase_display: LLO Management
phase_ordinal: 5
skills:
  - { name: llo-invite,      has_judge: false }
  - { name: llo-onboarding,  has_judge: false }
  - { name: llo-uat,         has_judge: false }
  - { name: llo-launch,      has_judge: false }
recurring_skills:
  - { name: timeline-monitor,   has_judge: true }
  - { name: flw-data-review,    has_judge: true }
  - { name: ocs-chatbot-qa,     has_judge: false }
  - { name: ocs-chatbot-eval,   has_judge: true }
---

# Stub agent (frontmatter only — see apps/opps/tests/conftest.py)
