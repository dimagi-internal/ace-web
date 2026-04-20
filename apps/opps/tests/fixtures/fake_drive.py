"""An in-memory fake DriveClient for tests.

Serves a dict-shaped virtual file tree so sync / parser / view tests can run
without touching Google. The tree is keyed by (synthetic) folder id; files
and folders each get a synthetic id of the form `fake-<counter>` assigned at
tree build time.

Usage:

    tree = {
        "ACE": {
            "malaria-pilot": {
                "opp.yaml": "slug: malaria-pilot\\n...",
                "runs": {
                    "r1": {
                        "run.yaml": "...",
                    }
                }
            }
        }
    }
    client = FakeDriveClient.from_tree(tree)
    files = client.list_files(client.folder_id("ACE/malaria-pilot"))
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import count

from apps.opps.drive_client import DriveClient, DriveFile, FileContent


@dataclass
class _Node:
    id: str
    name: str
    parent_id: str | None
    mime_type: str               # "application/vnd.google-apps.folder" for folders
    body: str | None = None      # None for folders
    modified_time: str | None = None
    children: dict[str, _Node] = field(default_factory=dict)  # name -> node


class FakeDriveClient(DriveClient):
    """In-memory DriveClient for tests. Supports the methods the sync layer uses."""

    FOLDER_MIME = "application/vnd.google-apps.folder"

    def __init__(self):
        self._root = _Node(id="fake-root", name="", parent_id=None, mime_type=self.FOLDER_MIME)
        self._nodes_by_id: dict[str, _Node] = {"fake-root": self._root}
        self._counter = count(1)

    @classmethod
    def from_tree(cls, tree: dict) -> FakeDriveClient:
        client = cls()
        client._load(client._root, tree)
        return client

    def _load(self, parent: _Node, tree: dict):
        for name, value in tree.items():
            nid = f"fake-{next(self._counter)}"
            if isinstance(value, dict):
                node = _Node(
                    id=nid, name=name, parent_id=parent.id, mime_type=self.FOLDER_MIME
                )
                parent.children[name] = node
                self._nodes_by_id[nid] = node
                self._load(node, value)
            else:
                mime = self._guess_mime(name)
                node = _Node(
                    id=nid, name=name, parent_id=parent.id, mime_type=mime, body=str(value)
                )
                parent.children[name] = node
                self._nodes_by_id[nid] = node

    @staticmethod
    def _guess_mime(name: str) -> str:
        if name.endswith(".yaml") or name.endswith(".yml"):
            return "application/x-yaml"
        if name.endswith(".md"):
            return "text/markdown"
        if name.endswith(".jsonl") or name.endswith(".json"):
            return "application/json"
        return "text/plain"

    def folder_id(self, path: str) -> str:
        """Test helper: resolve a slash-separated path to a folder id."""
        node = self._root
        for part in path.strip("/").split("/"):
            node = node.children[part]
        return node.id

    def file_id(self, path: str) -> str:
        """Test helper: resolve a slash-separated path to a file id."""
        node = self._root
        for part in path.strip("/").split("/"):
            node = node.children[part]
        return node.id

    def set_modified_time(self, path: str, iso_timestamp: str) -> None:
        """Set modified_time on a file-by-path, for test ordering setups."""
        node = self._nodes_by_id[self.folder_id(path)]
        node.modified_time = iso_timestamp

    # --- DriveClient interface ---

    def list_files(
        self, folder_id: str, recursive: bool = False, page_size: int = 100
    ) -> list[DriveFile]:
        node = self._nodes_by_id[folder_id]
        results: list[DriveFile] = []
        self._list(node, "", recursive, results)
        return results

    def _list(self, node: _Node, prefix: str, recursive: bool, results: list):
        for name, child in node.children.items():
            child_path = f"{prefix}/{name}" if prefix else name
            if child.mime_type == self.FOLDER_MIME:
                if recursive:
                    self._list(child, child_path, True, results)
                else:
                    results.append(DriveFile(
                        id=child.id, name=name, mime_type=child.mime_type,
                        web_view_link=f"https://fake/{child.id}", path=child_path,
                        modified_time=child.modified_time,
                    ))
            else:
                results.append(DriveFile(
                    id=child.id, name=name, mime_type=child.mime_type,
                    web_view_link=f"https://fake/{child.id}", path=child_path,
                    modified_time=child.modified_time,
                ))

    def get_file(self, file_id: str) -> DriveFile:
        node = self._nodes_by_id[file_id]
        return DriveFile(
            id=node.id, name=node.name, mime_type=node.mime_type,
            web_view_link=f"https://fake/{node.id}", path=node.name,
            modified_time=node.modified_time,
        )

    def get_content(self, file_id: str, mime_type: str) -> FileContent:
        node = self._nodes_by_id[file_id]
        if node.body is None:
            raise ValueError(f"{node.name} is a folder, not a file")
        return FileContent(content=node.body, content_type=node.mime_type)

    # --- Write surface ---

    def create_folder(self, parent_id: str, name: str) -> str:
        parent = self._nodes_by_id[parent_id]
        if parent.mime_type != self.FOLDER_MIME:
            raise ValueError(f"{parent.name} is not a folder")
        nid = f"fake-{next(self._counter)}"
        node = _Node(
            id=nid, name=name, parent_id=parent.id, mime_type=self.FOLDER_MIME
        )
        parent.children[name] = node
        self._nodes_by_id[nid] = node
        return nid

    def upload_file(
        self, parent_id: str, name: str, content: str, mime_type: str
    ) -> str:
        parent = self._nodes_by_id[parent_id]
        if parent.mime_type != self.FOLDER_MIME:
            raise ValueError(f"{parent.name} is not a folder")
        nid = f"fake-{next(self._counter)}"
        node = _Node(
            id=nid, name=name, parent_id=parent.id, mime_type=mime_type, body=content
        )
        parent.children[name] = node
        self._nodes_by_id[nid] = node
        return nid

    def update_file(self, file_id: str, content: str, mime_type: str) -> None:
        node = self._nodes_by_id[file_id]
        if node.mime_type == self.FOLDER_MIME:
            raise ValueError(f"{node.name} is a folder, not a file")
        node.body = content
        node.mime_type = mime_type

    def copy_file(
        self, file_id: str, new_parent_id: str, new_name: str | None = None
    ) -> str:
        src = self._nodes_by_id[file_id]
        if src.mime_type == self.FOLDER_MIME:
            raise ValueError(f"{src.name} is a folder; copy_file copies files only")
        parent = self._nodes_by_id[new_parent_id]
        if parent.mime_type != self.FOLDER_MIME:
            raise ValueError(f"{parent.name} is not a folder")
        nid = f"fake-{next(self._counter)}"
        name = new_name or src.name
        node = _Node(
            id=nid, name=name, parent_id=parent.id,
            mime_type=src.mime_type, body=src.body,
        )
        parent.children[name] = node
        self._nodes_by_id[nid] = node
        return nid

    def trash_folder(self, folder_id: str) -> None:
        node = self._nodes_by_id.get(folder_id)
        if node is None or node.parent_id is None:
            return
        parent = self._nodes_by_id[node.parent_id]
        parent.children.pop(node.name, None)
        # Recursively drop descendants from the id index so get_file 404s.
        def _drop(n):
            for child in list(n.children.values()):
                _drop(child)
            self._nodes_by_id.pop(n.id, None)
        _drop(node)


# --- Realistic fixture builders ---

MALARIA_PILOT_IDD = """# Malaria Pilot IDD

Reduce malaria infant mortality in northern Mozambique via monthly
FLW-administered RDT screening and referral.
"""


def malaria_pilot_tree() -> dict:
    """Flat-layout fixture for malaria-pilot — the canonical shape that
    the ACE plugin (/ace:run) now writes and that ace-web reads.

    Contains a realistic spread of artifacts across the five flat
    subfolders mapped in ``_FLAT_SUBFOLDER_SKILLS`` so tests exercising
    the list view, workbench payload, and chat seed have data to hit.
    """
    return {
        "ACE": {
            "malaria-pilot": {
                "state.yaml": """current_phase: app-building
current_step: app-test
mode: review
started_at: 2026-04-01T10:00:00Z
created_by: neal@dimagi.com
display_name: Malaria Pilot — Northern Mozambique
""",
                "idea.md": "Seed idea for the malaria pilot.",
                "pdd.md": MALARIA_PILOT_IDD,
                "app-summaries": {
                    "learn-app-brief.md": "# Learn App Brief\n\n12 forms",
                    "deliver-app-brief.md": "# Deliver App\n\n4 workflows",
                },
                "test-results": {
                    "test-plan.md": "40 test cases",
                    "bug-list.md": "2 bugs found",
                },
                "training-materials": {
                    "facilitator-guide.md": "# Facilitator Guide\n\nOnboarding LLOs.",
                },
                "comms-log": {
                    "onboarding-email.md": "Welcome to the malaria pilot.",
                },
                "closeout": {
                    "cycle-grade.md": "# Cycle Grade\n\nOverall: B+",
                },
            }
        }
    }


# Back-compat alias — older tests referenced this name for the malaria
# fixture when the structured layout still existed. Flat-only now.
malaria_pilot_structured_tree = malaria_pilot_tree


def nutrition_legacy_flat_tree() -> dict:
    """Smaller flat-layout fixture for tests that want a second opp
    alongside malaria-pilot."""
    return {
        "ACE": {
            "nutrition-legacy": {
                "state.yaml": """current_phase: app-building
current_step: app-test
mode: review
started_at: 2026-03-20T09:00:00Z
""",
                "pdd.md": "# Nutrition IDD\n\nInfant nutrition monitoring in rural India.",
                "app-summaries": {
                    "learn-app-summary.md": "8 forms · 3 case types",
                    "deliver-app-summary.md": "3 service workflows",
                },
                "test-results": {
                    "test-plan.md": "40 test cases",
                    "bug-list.md": "2 bugs found",
                },
            }
        }
    }


def web_created_opp_tree() -> dict:
    """Flat-layout fixture that mimics what opp_creator.create_opp writes
    today (since 2026-04-20): idea.md at root, no runs/ subfolder."""
    return {
        "ACE": {
            "turmeric-smoketest-20260418-1114": {
                "idea.md": "# Turmeric Market Survey\n\nFLWs photograph turmeric vendors.",
            }
        }
    }


def opp_with_scorecard_tree() -> dict:
    """Flat-layout fixture with an opp-eval scorecard, verdict, and trend.

    Covers the umbrella-eval surfaces the plugin writes:
      - ``verdicts/opp-eval-deep.yaml``   — machine-readable
      - ``scorecards/2026-04-15-opp-eval-deep.md`` — human-readable
      - ``scorecards/trend.md``           — rolling trend

    Also includes a per-skill ``verdicts/ocs-chatbot-eval-deep.yaml`` so
    judge-verdict surfacing on step rows can be exercised alongside the
    run-level scorecard.
    """
    return {
        "ACE": {
            "cholera-smoketest": {
                "state.yaml": """current_phase: llo-management
current_step: llo-launch
mode: review
started_at: 2026-04-10T10:00:00Z
initiated_by: neal@dimagi.com
last_actor: ace@dimagi-ai.com
last_actor_at: 2026-04-15T15:30:00Z
gates:
  idea-to-pdd:
    decision: approved
    decided_by: neal@dimagi.com
    decided_at: 2026-04-10T11:00:00Z
    note: PDD passes EM stress test
""",
                "idea.md": "Cholera outbreak response pilot.",
                "pdd.md": "# Cholera Response PDD\n\nRapid detection and referral.",
                "verdicts": {
                    "opp-eval-deep.yaml": """skill: opp-eval
mode: deep
ran_at: 2026-04-15T14:00:00Z
overall_score: 82
verdict: pass
dimensions:
  design: {score: 88, strength: "clear EM", weakness: "thin appendix"}
  build: {score: 80, strength: "both apps built", weakness: "1 bug open"}
  content: {score: 85, strength: "good training", weakness: "FAQ sparse"}
  ocs: {score: 75, strength: "deep gate passed", weakness: "low tagging"}
summary: "Run is healthy; improvement path is OCS tagging and PDD appendix depth."
""",
                    "ocs-chatbot-eval-deep.yaml": """skill: ocs-chatbot-eval
mode: deep
ran_at: 2026-04-14T10:00:00Z
overall_score: 78
verdict: pass
dimensions:
  correctness: {score: 82}
  source_usage: {score: 74}
  tone: {score: 80}
  tagging: {score: 70}
""",
                },
                "gate-briefs": {
                    "idea-to-pdd.md": """# Gate brief: idea-to-pdd

- [x] EM specified with 3+ outcomes
- [ ] Stress-test appendix has >= 5 entries
- [x] Archetype mapped

## Concerns
- Appendix has only 3 entries — tighten before approval.
""",
                },
                "scorecards": {
                    "2026-04-15-opp-eval-deep.md": """# opp-eval deep — 2026-04-15

Overall: **82/100** (pass)

| Dimension | Score | Strength | Weakness |
|---|---|---|---|
| design | 88 | clear EM | thin appendix |
| build | 80 | both apps built | 1 bug open |
| content | 85 | good training | FAQ sparse |
| ocs | 75 | deep gate passed | low tagging |

## Recommendations
1. Deepen PDD stress-test appendix
2. Tune OCS tagging prompts
""",
                    "trend.md": """# opp-eval trend

| Date | Overall | design | build | content | ocs |
|---|---|---|---|---|---|
| 2026-04-10 | 74 | 80 | 72 | 78 | 66 |
| 2026-04-12 | 78 | 84 | 76 | 82 | 70 |
| 2026-04-15 | 82 | 88 | 80 | 85 | 75 |
""",
                },
            }
        }
    }
