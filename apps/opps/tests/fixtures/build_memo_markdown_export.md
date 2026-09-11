# Build memo — Poverty Graduation · run 20260911-0900

This is the build memo for this run: every place ACE exercised \[ACE\] latitude and every ambiguity it hit in \[FIXED\] material while building the apps and the Connect opportunity. Targeting PDD §11 \[FIXED\] names it: "The build memo is the review artifact: humans review the memo and spot-check the apps, rather than reviewing every screen."

**How to review:** work through section 1\. Each row says where to spot-check it in the apps or on Connect. Sections 2–4 are the producers' own memos, for context.

## 1\. Every \[ACE\] latitude taken and every \[FIXED\] ambiguity hit

| \# | Kind | PDD section | What ACE did | Where to spot-check | From |
| :---- | :---- | :---- | :---- | :---- | :---- |
| 1 | \[ACE\] latitude | Deliver PDD §4.2 | Split the household roster into its own form so a visit can resume mid-roster | Deliver app → Household visit → Roster | Deliver memo |
| 2 | \[FIXED\] ambiguity | Targeting PDD §7 | PDD says "score ≥ 3 **or** consent"; applied as score ≥ 3 AND consent\_confirmed \= yes | Deliver app → Eligibility → `eligible` | Deliver memo |
| 3 | open item | NOT CITED by pdd-to-learn-app | Quiz pass mark left at Connect's default (80%) | Connect → Learn settings → passing score | Learn memo |
| 4 | decision | Work order §3 | Per-visit rate USD 4.00 | Connect → Payment units | decisions.yaml: payment-rate |

## 2\. Deliver app

### Build memo

- Household roster is a repeat group of up to 12 members.  
- GPS is captured on the first question of every visit.

## 3\. Learn app

### Framework gaps (Learn PDD §6(5))

None applies: every module maps to a Targeting PDD section.

## 4\. Opportunity configuration and verification flags

| Verification rule | Where applied |
| :---- | :---- |
| Duplicate submission | Not configurable on Connect |
| GPS radius 200 m | NOT STATED by connect-opp-setup |

## 5\. Completeness

| Input | Status | If not present |
| :---- | :---- | :---- |
| 3-commcare/pdd-to-deliver-app\_summary.md (\#\# Build memo) | present | — |
| 3-commcare/pdd-to-learn-app\_build-memo.md | present | — |
| 4-connect/connect-opp-setup.md (\#\# Build memo — opportunity configuration and verification) | section missing | Re-run `/ace:step connect-opp-setup poverty-graduation/20260911-0900`, then `/ace:step build-memo poverty-graduation/20260911-0900` |

