# Learning: GitHub squash-merge from a stale branch silently orphans intervening commits

**Date**: 2026-05-12
**Context**: PR #309 (mobile stop busy-guard) showed up on GitHub as MERGED but the contract was never on `main`. Surfaced during the cloud-emulator code review (2026-05-12). Repo-wide squash merges have been disabled in response; see the Fix section.
**Status**: Active (defense in place: `allow_squash_merge=false`)

## Problem

A merged PR can disappear from `main`'s working tree even though GitHub shows
its `state: MERGED` with a `mergeCommit.oid`. Symptom: the merge commit and
its parent are reachable in the object DAG, but
`git merge-base --is-ancestor <merge-commit> origin/main` returns no, and
the changes are absent from the live tree.

Concrete instance (2026-05-12):

```
PR #309 — feat(mobile): stop refuses mid-run by default; force=true to bypass
  state: MERGED
  mergedAt: 2026-05-12T03:04:28Z
  mergeCommit.oid: 2d6d9c2  ← orphaned

git merge-base --is-ancestor 2d6d9c2 origin/main  →  NO
git log --oneline -- apps/mobile/views.py        →  no #309 changes
```

The 30 lines of stop busy-guard logic the PR added were not in main even
though GitHub's PR page said they were.

## Root cause

GitHub's **squash merge** does not 3-way merge. It collapses the topic
branch's commits into a single commit whose parent is the **base ref's
current tip from the topic branch's view**, then fast-forwards `main` to
that new commit.

Concretely with the #309 incident:

1. 2026-05-12 03:04 — PR #309 (`stop-busy-guard`) merged with a true merge
   commit (2d6d9c2). `main` advances to 2d6d9c2.
2. 2026-05-12 03:07 — PR #311 (`run-recipe-structured-steps`) merged. **PR
   #311's topic branch had been forked from main *before* #309 landed.**
   #311 was configured to merge via **squash**.
3. The squash-merge logic took #311's three commits, replayed them on top of
   `be45e15` (the PR-#310 merge — i.e. #311's branch's view of main), and
   wrote the result (`0c7c1fc`) as the new tip of `main`. The merge commit
   from #309 is no longer reachable.

The orphaning happened silently — no conflict because the squash never tried
to 3-way merge. GitHub's PR page still showed `state: MERGED` for #309
because the merge commit existed in the object database; nothing connected
the dots that it was no longer in the lineage.

## Why this is dangerous

- **Silent.** Neither author, merger, nor reviewer sees a warning. The
  affected PR keeps its green "Merged" badge.
- **Easy to trigger.** The parallel agent cadence — many small PRs against
  the same files, branches sometimes hours stale — is exactly the condition
  squash-from-stale-branch needs.
- **Hard to detect.** You only notice when the *behavior* the lost PR was
  supposed to deliver doesn't show up at runtime. In #309's case, that was
  weeks later in a code review that compared the live `stop` view against
  the PR's intended diff.

## Fix shipped

Repo-wide disable of squash merges (2026-05-12):

```
gh api -X PATCH repos/jjackson/ace-web -F allow_squash_merge=false
```

Merge commits and rebase merges can't reproduce the orphaning because both
explicitly thread the existing main into the new history:

- **Merge commit**: two-parent commit; later merges from sibling branches
  produce conflicts (visible) instead of silent drops.
- **Rebase merge**: replays topic commits on the current main tip, so
  intervening merges are picked up.

The verified repo settings after the fix:

| Setting | Value |
|---|---|
| `allow_squash_merge` | `false` ← off |
| `allow_merge_commit` | `true` |
| `allow_rebase_merge` | `true` |
| `allow_auto_merge` | `true` |
| `delete_branch_on_merge` | `true` |

## How to apply

- **Don't re-enable `allow_squash_merge`** without the mitigations below.
- If you do need to re-enable it (e.g. team preference for one-commit-per-PR
  history), also enable **"Always suggest updating pull request branches"**
  (`allow_update_branch=true`) and require branches to be up-to-date before
  merge via a branch-protection rule on `main`. That forces a rebase before
  the squash, which closes the stale-base vector.
- For one-off recovery of an orphaned PR: re-implement the contract on top
  of current main and merge fresh. Don't try to cherry-pick the orphaned
  commit if its branch is stale — the same drift that caused the orphaning
  will probably reappear. (We did this for #309 → #317 on 2026-05-12.)

## How to spot it after the fact

`gh pr view <N> --json state,mergeCommit,mergedAt` reports `state: MERGED`
even for orphaned PRs. The reliable check:

```bash
gh pr view <N> --json mergeCommit --jq '.mergeCommit.oid' \
  | xargs -I{} git merge-base --is-ancestor {} origin/main \
  && echo "still in main" \
  || echo "ORPHANED"
```

When parallel PRs cluster around the same files and you suspect a drop,
this check on each recently-merged PR will surface any silent losses.
