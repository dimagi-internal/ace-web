"""Build a seed "system message" for a new ace-web chat session launched
from the Workbench's 'Discuss in chat' CTA.

The seed is rendered as markdown and includes:
- A preamble explaining the improvement loop so Claude knows it can propose
  a SKILL.md edit and (if the chat has the tools) push it to GitHub.
- The opp's IDD excerpt (up to IDD_MAX_CHARS characters).
- The target step's artifacts, with their bodies inlined (each capped to
  ARTIFACT_MAX_CHARS).
- The latest judge verdict (score, criteria, rationale) if present.
- A pointer to the SKILL.md file in the ace plugin repo.

This is a pure function — it takes a DriveClient so it can fetch artifact
bodies, but it never writes to Drive and never talks to Django models.
"""
from __future__ import annotations

from apps.opps.drive_client import DriveClient
from apps.opps.sync import OppSnapshot

IDD_MAX_CHARS = 8000          # ~2k tokens
ARTIFACT_MAX_CHARS = 8000
PREAMBLE = """\
You have been dropped into a chat about a specific step of an ACE opportunity run.
The user wants to iterate on the output below — understand what went wrong (or what
could be better), and then if appropriate propose an edit to the skill's SKILL.md
file in the ace plugin repo. If you have git/gh tools in this session, you may
create a commit and open a PR against the plugin. This is the "improvement loop":
inspect → discuss → edit SKILL.md → re-run ACE → compare.
"""


def build_chat_seed(
    snap: OppSnapshot,
    *,
    skill: str,
    drive_client: DriveClient,
    skill_md_path: str,
    workbench_url: str | None = None,
) -> str:
    """Return a markdown-formatted seed message for the new chat session.

    ``workbench_url`` (optional) is a deep-link back to the originating step
    page in the ace-web Workbench (``/w/<workspace>/opps/<slug>/runs/<run>/steps/<skill>``).
    When provided, it's surfaced near the top of the seed so a user reopening
    the chat days later can navigate back to the step they were debating.
    """
    step_snap = next(
        (s for s in snap.current_run.steps if s.step.skill_name == skill), None
    )
    if step_snap is None:
        raise ValueError(
            f"no step {skill!r} in run {snap.current_run.run_id!r} for opp {snap.opp.slug!r}"
        )

    sections: list[str] = []

    sections.append(
        f"# Discussing `{skill}` — opp `{snap.opp.slug}`, run `{snap.current_run.run_id}`"
    )
    sections.append(PREAMBLE.strip())

    if workbench_url:
        sections.append(f"**View in Workbench:** [{workbench_url}]({workbench_url})")

    sections.append(
        f"**Skill source:** `{skill_md_path}` (edit this file to improve the skill)"
    )

    # IDD excerpt
    sections.append("## IDD")
    sections.append(f"```markdown\n{snap.pdd_body[:IDD_MAX_CHARS]}\n```")

    # Artifacts
    if step_snap.artifacts:
        sections.append("## Artifacts")
        for artifact in step_snap.artifacts:
            try:
                content = drive_client.get_content(
                    artifact.drive_file_id, artifact.mime_type
                )
                body = content.content[:ARTIFACT_MAX_CHARS]
            except Exception as exc:
                body = f"(failed to fetch body: {exc})"
            sections.append(f"### `{artifact.name}`")
            sections.append(f"```\n{body}\n```")
    else:
        sections.append("## Artifacts")
        sections.append("_no artifacts for this step_")

    # Judge verdict
    if step_snap.judge is not None:
        j = step_snap.judge
        sections.append("## Judge verdict")
        score_line = f"**score:** {j.score} · **passed:** {j.passed}"
        sections.append(score_line)
        if j.criteria:
            sections.append("**criteria:**")
            for key, value in j.criteria.items():
                sections.append(f"- {key}: {value}")
        if j.rationale:
            sections.append("**rationale:**")
            sections.append(f"> {j.rationale}")

    return "\n\n".join(sections)
