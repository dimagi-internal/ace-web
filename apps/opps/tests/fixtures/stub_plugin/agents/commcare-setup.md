---
name: commcare-setup
description: >
  Phase 2 of the CRISPR-Connect lifecycle: translate the approved PDD into
  Learn and Deliver apps via Nova, deploy them to CommCare HQ, test, and
  generate training materials.
model: inherit
phase: commcare-setup
phase_display: CommCare Setup
phase_ordinal: 2
skills:
  - { name: pdd-to-learn-app,    has_judge: true }
  - { name: pdd-to-deliver-app,  has_judge: true }
  - { name: app-deploy,          has_judge: false }
  - { name: app-test,            has_judge: true }
  - { name: training-materials,  has_judge: true }
---

# Stub agent (frontmatter only — see apps/opps/tests/conftest.py)
