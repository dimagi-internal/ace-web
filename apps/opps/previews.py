"""Per-skill preview_text extractors.

Each extractor turns one step's artifact body (already fetched by the sync
layer) into a short one-line string rendered in the Workbench center-pane
row. The mapping from skill name to extractor lives in `PREVIEW_EXTRACTORS`.

Extractors are pure — they take (StepSnapshot, bodies: dict[str, str]) and
return a string. They never call Drive.
"""
from __future__ import annotations

import re
from collections.abc import Callable

import yaml

from apps.opps.sync import StepSnapshot

PreviewFn = Callable[[StepSnapshot, dict[str, str]], str]


# --- Individual extractors ---

def _first_nonblank_line(body: str) -> str:
    for line in body.splitlines():
        stripped = line.strip().lstrip("# ").strip()
        if stripped:
            return stripped
    return ""


def _idea_to_idd(step: StepSnapshot, bodies: dict[str, str]) -> str:
    # IDD→PDD rename transition: accept either primary-doc filename.
    body = bodies.get("pdd.md") or bodies.get("idd.md", "")
    # Try to skip the heading and grab the first sentence of the body.
    after_heading = body.split("\n\n", 1)[-1] if "\n\n" in body else body
    first_sentence = after_heading.strip().split(". ")[0].strip()
    if not first_sentence:
        return "📄 pdd.md"
    return f"📄 pdd.md — \"{first_sentence[:140]}\""


def _idd_to_learn_app(step: StepSnapshot, bodies: dict[str, str]) -> str:
    body = bodies.get("learn-app-brief.md", "")
    forms_match = re.search(r"(\d+)\s*forms?", body)
    questions_match = re.search(r"(\d+)\s*questions?", body)
    cases_match = re.search(r"(\d+)\s*case\s*types?", body)
    parts = []
    if forms_match:
        parts.append(f"{forms_match.group(1)} forms")
    if questions_match:
        parts.append(f"{questions_match.group(1)} questions")
    if cases_match:
        parts.append(f"{cases_match.group(1)} case types")
    if not parts:
        return "📦 learn-app-brief.md"
    return "📦 " + " · ".join(parts)


def _idd_to_deliver_app(step: StepSnapshot, bodies: dict[str, str]) -> str:
    body = bodies.get("deliver-app-brief.md", "")
    flows = re.search(r"(\d+)\s*(?:service\s*)?workflows?", body)
    triggers = re.search(r"(\d+)\s*payment\s*triggers?", body)
    parts = []
    if flows:
        parts.append(f"{flows.group(1)} workflows")
    if triggers:
        parts.append(f"{triggers.group(1)} payment triggers")
    if not parts:
        return "📦 deliver-app-brief.md"
    return "📦 " + " · ".join(parts)


def _app_deploy(step: StepSnapshot, bodies: dict[str, str]) -> str:
    body = bodies.get("deploy-summary.md", "")
    apps = re.search(r"(\d+)\s*apps?\s*packaged", body)
    status_line = ""
    for line in body.splitlines():
        if "status" in line.lower() or "awaiting" in line.lower():
            status_line = line.strip()
            break
    if apps:
        return f"📄 {apps.group(1)} apps packaged · {status_line or 'see summary'}"
    return "📄 deploy-summary.md"


def _app_test(step: StepSnapshot, bodies: dict[str, str]) -> str:
    body = bodies.get("test-results.yaml", "")
    try:
        data = yaml.safe_load(body) or {}
    except yaml.YAMLError:
        data = {}
    passed = data.get("passed")
    failed = data.get("failed")
    total = data.get("total")
    if passed is not None and total is not None:
        fail_str = f" · {failed} fail" if failed else ""
        return f"🧪 {passed}/{total} pass{fail_str}"
    return "🧪 test-results"


def _training_materials(step: StepSnapshot, bodies: dict[str, str]) -> str:
    n = len(step.artifacts)
    return f"📚 {n} doc{'s' if n != 1 else ''}"


def _connect_program_setup(step: StepSnapshot, bodies: dict[str, str]) -> str:
    body = bodies.get("program-config.md", "")
    first = _first_nonblank_line(body)
    return f"🔧 {first[:100]}" if first else "🔧 program-config.md"


def _connect_opp_setup(step: StepSnapshot, bodies: dict[str, str]) -> str:
    body = bodies.get("opp-config.md", "")
    rules = re.search(r"(\d+)\s*(?:verification\s*)?rules?", body)
    units = re.search(r"(\d+)\s*(?:delivery\s*)?units?", body)
    parts = []
    if rules:
        parts.append(f"{rules.group(1)} rules")
    if units:
        parts.append(f"{units.group(1)} units")
    if not parts:
        return "🔧 opp-config.md"
    return "🔧 " + " · ".join(parts)


def _llo_invite(step: StepSnapshot, bodies: dict[str, str]) -> str:
    body = bodies.get("invite-list.md", "")
    # Count bullet-point lines as LLO candidates.
    count = sum(1 for line in body.splitlines() if line.strip().startswith(("-", "*")))
    if count:
        return f"📧 {count} candidate LLO{'s' if count != 1 else ''}"
    return "📧 invite-list.md"


def _llo_onboarding(step: StepSnapshot, bodies: dict[str, str]) -> str:
    n = len(step.artifacts)
    return f"📧 {n} onboarding email{'s' if n != 1 else ''}"


def _llo_uat(step: StepSnapshot, bodies: dict[str, str]) -> str:
    return "🧪 UAT protocol" if step.artifacts else "—"


def _llo_launch(step: StepSnapshot, bodies: dict[str, str]) -> str:
    return "🚀 launch checklist" if step.artifacts else "—"


def _ocs_agent_setup(step: StepSnapshot, bodies: dict[str, str]) -> str:
    body = bodies.get("ocs-context.md", "")
    n_lines = len([line for line in body.splitlines() if line.strip()])
    if n_lines:
        return f"🤖 OCS agent · {n_lines}-line context"
    return "🤖 ocs-context.md"


def _timeline_monitor(step: StepSnapshot, bodies: dict[str, str]) -> str:
    body = bodies.get("timeline-report.md", "")
    first = _first_nonblank_line(body)
    return f"📅 {first[:100]}" if first else "📅 timeline-report.md"


def _flw_data_review(step: StepSnapshot, bodies: dict[str, str]) -> str:
    body = bodies.get("flw-review.md", "")
    subs = re.search(r"(\d+)\s*submissions?", body)
    if subs:
        return f"📊 {subs.group(1)} submissions reviewed"
    return "📊 flw-review.md"


def _opp_closeout(step: StepSnapshot, bodies: dict[str, str]) -> str:
    body = bodies.get("invoice-summary.md", "")
    amount = re.search(r"\$[\d,]+(?:\.\d{2})?", body)
    if amount:
        return f"💰 invoice: {amount.group(0)}"
    return "💰 invoice-summary.md"


def _llo_feedback(step: StepSnapshot, bodies: dict[str, str]) -> str:
    body = bodies.get("feedback-report.md", "")
    responses = re.search(r"(\d+)/(\d+)\s*responses?", body)
    if responses:
        return f"📝 {responses.group(0)} collected"
    return "📝 feedback-report.md"


def _learnings_summary(step: StepSnapshot, bodies: dict[str, str]) -> str:
    body = bodies.get("learnings.md", "")
    n_items = sum(
        1 for line in body.splitlines() if line.strip().startswith(("-", "*"))
    )
    if n_items:
        return f"💡 {n_items} learning{'s' if n_items != 1 else ''}"
    return "💡 learnings.md"


def _cycle_grade(step: StepSnapshot, bodies: dict[str, str]) -> str:
    body = bodies.get("grade-report.md") or bodies.get("closeout/cycle-grade.md", "")
    try:
        data = yaml.safe_load(body) or {}
    except yaml.YAMLError:
        data = {}
    grade = data.get("overall_grade")
    if grade is not None:
        return f"🏆 {grade}/10"
    match = re.search(r"(\d+\.?\d*)\s*/\s*10", body)
    if match:
        return f"🏆 {match.group(1)}/10"
    return "🏆 grade-report.md"


# --- New extractors for skills the plugin added post-0.3.5 ---


def _pdd_to_test_prompts(step: StepSnapshot, bodies: dict[str, str]) -> str:
    body = bodies.get("test-prompts.md", "")
    # Q&A pairs are usually headings starting with "## Q" or bullets with "Q:".
    count = len(re.findall(r"(?:^##\s+Q|^\s*-\s*\*\*Q)", body, re.MULTILINE))
    if count:
        return f"❓ {count} test prompt{'s' if count != 1 else ''}"
    return "❓ test-prompts.md"


def _ocs_chatbot_qa(step: StepSnapshot, bodies: dict[str, str]) -> str:
    # ocs-chatbot-qa produces qa-captures/YYYY-MM-DD-ocs-chat-*.md. The
    # sync layer feeds artifact bodies keyed by filename (basename), so
    # look at the newest capture body if available.
    names = sorted((a.name for a in step.artifacts), reverse=True)
    newest = next((n for n in names if n.endswith(".md")), None)
    if not newest:
        return "🧪 ocs-chatbot-qa"
    body = bodies.get(newest, "")
    # Transcripts mark structural pass/fail per prompt. Count them.
    passes = len(re.findall(r"structural[:\s-]*pass", body, re.IGNORECASE))
    fails = len(re.findall(r"structural[:\s-]*fail", body, re.IGNORECASE))
    if passes or fails:
        return f"🧪 {passes} pass · {fails} fail"
    variant = "deep" if "deep" in newest else ("quick" if "quick" in newest else "monitor")
    return f"🧪 capture ({variant})"


def _ocs_chatbot_eval(step: StepSnapshot, bodies: dict[str, str]) -> str:
    # The skill list row already shows the judge bar + numeric score in
    # its own column for has_judge skills. Don't duplicate the number
    # here on a different scale (the previous "{score:.0f}/100" looked
    # like 9/100 next to a green 8.5 bar). Just say pass / fail.
    judge = step.judge
    if judge is not None and judge.passed is True:
        return "⚖️ pass"
    if judge is not None and judge.passed is False:
        return "⚖️ fail"
    return "⚖️ pending"


def _opp_eval(step: StepSnapshot, bodies: dict[str, str]) -> str:
    judge = step.judge
    if judge is not None and judge.score is not None:
        return f"🏁 run score {judge.score:.0f}/100"
    # Fall back to scorecard body if present.
    names = sorted((a.name for a in step.artifacts), reverse=True)
    newest = next((n for n in names if n.endswith(".md") and n != "trend.md"), None)
    if not newest:
        return "🏁 opp-eval"
    body = bodies.get(newest, "")
    match = re.search(r"(?:overall|run\s+score)[:\s]+(\d+(?:\.\d+)?)", body, re.IGNORECASE)
    if match:
        return f"🏁 run score {match.group(1)}"
    return "🏁 scorecard"


# --- Registry + public entry point ---

PREVIEW_EXTRACTORS: dict[str, PreviewFn] = {
    "idea-to-pdd":           _idea_to_idd,
    "pdd-to-test-prompts":   _pdd_to_test_prompts,
    "pdd-to-learn-app":      _idd_to_learn_app,
    "pdd-to-deliver-app":    _idd_to_deliver_app,
    "app-deploy":            _app_deploy,
    "app-test":              _app_test,
    "training-materials":    _training_materials,
    "connect-program-setup": _connect_program_setup,
    "connect-opp-setup":     _connect_opp_setup,
    "llo-invite":            _llo_invite,
    "llo-onboarding":        _llo_onboarding,
    "llo-uat":               _llo_uat,
    "llo-launch":            _llo_launch,
    "ocs-agent-setup":       _ocs_agent_setup,
    "ocs-chatbot-qa":        _ocs_chatbot_qa,
    "ocs-chatbot-eval":      _ocs_chatbot_eval,
    "opp-eval":              _opp_eval,
    "timeline-monitor":      _timeline_monitor,
    "flw-data-review":       _flw_data_review,
    "opp-closeout":          _opp_closeout,
    "llo-feedback":          _llo_feedback,
    "learnings-summary":     _learnings_summary,
    "cycle-grade":           _cycle_grade,
}


def build_preview(step: StepSnapshot, bodies: dict[str, str]) -> str:
    """Return the one-line preview_text for a step.

    Prefers a dedicated extractor if registered; falls back to an artifact count
    ("N artifacts") or a dash if there are none.
    """
    extractor = PREVIEW_EXTRACTORS.get(step.step.skill_name)
    if extractor is not None and step.artifacts:
        try:
            return extractor(step, bodies)
        except Exception:  # noqa: BLE001 — never crash the view on a bad preview
            pass
    if not step.artifacts:
        return "—"
    n = len(step.artifacts)
    return f"{n} artifact{'s' if n != 1 else ''}"
