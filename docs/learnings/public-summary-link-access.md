# Gated links on the public run summary: tag them, never hide them

**Status:** convention, 2026-08-14. Enforced by
`apps/opps/tests/test_summary.py::test_every_gated_link_declares_admin_access`
and `::test_drive_deliverables_are_not_tagged_admin`.

## The ruling

> "Nothing is 'Dimagi only' at scale for ACE, even if right now it needs to be
> because of shared tenancy. For now we can show the link but have a tag on it
> (admin only)." — Jonathan, 2026-08-14

The public per-run summary (`/opps/:workspace/:slug/runs/:runId/summary`) is
ACE's external review surface. Most of what it links needs a Dimagi account
today. There are exactly three things you can do about that, and two are wrong:

| | what an outsider sees | verdict |
|---|---|---|
| Let it 404 / redirect | indistinguishable from "this run doesn't exist" | wrong (#707 fixed one of these) |
| Hide it from non-members | a thinner run than we actually built | wrong (#707 *introduced* this) |
| Show it, tagged `admin only` | the truth | **do this** |

The second one is the subtle failure. #707 removed the Workbench link from the
public payload because it 404s anonymously — which was an improvement over a
dead link, and still understated the run. Hiding is a quieter version of the
same lie.

## The mechanism

**Access is a property of the payload, not a hostname table in the component.**
The URLs change every run; the access model of the *system behind them* does
not. So each reader in `apps/opps/summary.py` declares the access of the link
it just produced, at the point where it knows which system that link points
into:

```python
"access": ACCESS_ADMIN,   # or ACCESS_PUBLIC
```

`viewer.is_member` rides along on the payload and decides only whether the page
*draws* the tag — a member already knows which links are internal, so tagging
them there is noise. Member and public payloads stay cached under separate
keys (`opp-summary:v2:{member|public}:…`), as they were before.

Do not reintroduce an `include_internal_links`-style flag that changes *which*
links are served. Membership changes the tag, not the content.

### Current classification

`admin` (verified anonymously on `spark-facilitator/20260813-2126`):

- CommCare HQ app pages — project-space membership; a signed-in non-member gets 404
- Connect opportunity — workspace membership
- OCS console (`admin_url`) — team membership. The chat *widget* is not gated;
  see `public-summary-embed-key.md`
- connect-labs dashboards + solicitations — redirect to a CommCare-HQ OAuth
  login an external partner can't self-serve
- the ace-web Workbench — workspace membership, and ace-web admits @dimagi.com only

`public`:

- Google Drive **deliverables** (PDD, work order, training pack, learnings,
  feedback ledgers). Their ACL is per-file and `/ace:share-run-access` shares
  exactly these with reviewers, so claiming "admin only" would be a guess in
  the wrong direction.
- Published walkthroughs — a Drive file or a canopy-web share minted with a
  link-visibility token; both circulate by design.

Drive **working** artifacts are the exception that proves the rule:
`open-questions.md` and `decisions.yaml` are never shared, so the payload
carries their **content** and tags the link `admin`. A tag on a link nobody can
open is not a substitute for the information in it.
