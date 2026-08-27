# Gated links on the public run summary: tag them, never hide them

**Status:** convention, 2026-08-14; **amended 2026-08-26 (ace-web#740) — a
Drive link's tag is now MEASURED, not asserted.** Enforced by
`apps/opps/tests/test_summary.py::test_an_unreachable_document_is_not_tagged_public`,
`::test_an_unreadable_acl_is_unknown_rather_than_public`,
`::test_every_gated_link_declares_admin_access`, and
`apps/opps/tests/test_drive_link_shared.py`.

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

- Published walkthroughs — a Drive file or a canopy-web share minted with a
  link-visibility token; both circulate by design. A canopy-web OPERATOR URL
  is the exception and derives `admin` (`_derive_walkthrough_access`).

Drive **working** artifacts still carry their **content**, not just a link:
`open-questions.md` and `decisions.yaml` are rendered on the page because a
tag on a link nobody can open is not a substitute for the information in it.
That part is unchanged; what changed is that their tag is measured too.

## Amendment, 2026-08-26 — a Drive link's tag is measured (ace-web#740)

The table above originally read: Google Drive **deliverables** (PDD, work
order, training pack, learnings, feedback ledgers) are `public`, because their
ACL is per-file and `/ace:share-run-access` shares exactly these with
reviewers. That is a claim about a workflow, not about a file — and the
workflow does not always run.

An anonymous audit of `spark-facilitator/20260820-0817` measured it:

```
design.docs[0].access = "public"
curl .../document/d/1GO6_A7mcDB5vuIHCZjo1ShXECco1sAqEdRXSYmWipzU/export?format=txt -> 401
curl .../document/d/1AZnIR0j4Sq9_TAXgxOpNiYQVXuUGXUe-rIEwQxnPyiQ/export?format=txt -> 401
```

Both rendered as **Open** and gave the reader *"You need access."* on the one
page we hand to people with no Dimagi account. Its verdict was NOT SAFE TO
SHARE. On the same run the training pack **was** anonymously reachable — which
is the point: one blanket tag could not have been right for both, and the
assertion was never evidence of anything either way.

So a Drive link's tag now comes from the file's own ACL:

- `apps/opps/drive_client.py::DriveClient.link_shared` — an `anyone`
  permission means the link opens without an account.
- `apps/opps/summary.py::LinkAccessReader` — one batched, concurrent, cached
  read per payload, primed before the section readers run so this does not
  undo the batching in ace-web#738.

**Use `permissions.list`, not `files.get(fields="permissions")`.** The latter
was tried first and returns an EMPTY list for every file on the ACE shared
drive, including ones that are demonstrably anyone-with-link readable — a
reader built on it would have called every deliverable admin-only. Verified
live 2026-08-26: the training LLO guide carries
`{'id': 'anyoneWithLink', 'type': 'anyone', 'role': 'commenter'}` and the PDD
carries no `anyone` entry at all. Note `commenter`, not `reader`: the check is
on `type` alone.

### The vocabulary gained a third value

`unknown` — the ACL could not be read. `public` would be the original bug with
an extra step; `admin` would invent a wall that may not exist, which this
document already calls "a guess in the wrong direction". It renders as an
`access unverified` tag rather than as silence, because an *untagged* link
reads to an outsider as "anyone can open this" — which is exactly what shipped.

Both consumers were updated in the same commit, as the frozen contract
requires: `frontend/src/api/oppSummary.ts`'s `LinkAccess` and
`apps/opps/tests/test_public_surface_contract.py`. The ACE plugin's anonymous
auditor is unaffected — its `LINK-ACCESS-MISLABELLED` rule fires on "the page
says `public`, an outsider gets a gate", so a tag that is not `public` cannot
trip it.

### What did NOT change

**Non-Drive links stay asserted, and should.** CommCare HQ app pages, the
Connect opportunity, the OCS console and connect-labs are gated by membership
in those systems — a property of the system, not of the object, with nothing
per-object to read. The original ruling in "The mechanism" above stands for
them verbatim.

**Do not fix a mislabelled link by changing the document's sharing.** Whether
a deliverable is disclosed to a partner is the operator's call, not the
renderer's. The page's job is to say what is true.
