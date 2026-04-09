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
                    ))
            else:
                results.append(DriveFile(
                    id=child.id, name=name, mime_type=child.mime_type,
                    web_view_link=f"https://fake/{child.id}", path=child_path,
                ))

    def get_file(self, file_id: str) -> DriveFile:
        node = self._nodes_by_id[file_id]
        return DriveFile(
            id=node.id, name=node.name, mime_type=node.mime_type,
            web_view_link=f"https://fake/{node.id}", path=node.name,
        )

    def get_content(self, file_id: str, mime_type: str) -> FileContent:
        node = self._nodes_by_id[file_id]
        if node.body is None:
            raise ValueError(f"{node.name} is a folder, not a file")
        return FileContent(content=node.body, content_type=node.mime_type)


# --- Realistic fixture builders ---

MALARIA_PILOT_IDD = """# Malaria Pilot IDD

Reduce malaria infant mortality in northern Mozambique via monthly
FLW-administered RDT screening and referral.
"""


def _step_yaml(skill: str, phase: str, ordinal: int, status: str = "complete") -> str:
    return f"""skill_name: {skill}
phase: {phase}
ordinal: {ordinal}
status: {status}
started_at: 2026-04-06T10:00:00Z
completed_at: 2026-04-06T10:05:00Z
"""


def _judge_yaml(score: float, rationale: str = "solid") -> str:
    return f"""score: {score}
passed: true
evaluated_at: 2026-04-06T10:05:00Z
criteria:
  completeness: {score}
  specificity: {score}
rationale: |
  {rationale}
"""


def malaria_pilot_structured_tree() -> dict:
    """Two-run structured fixture for malaria-pilot.

    Run 2026-04-01-001: older run, idd-to-learn-app judge 7.1
    Run 2026-04-06-002: newer run, idd-to-learn-app judge 8.5 (improved)
    """
    return {
        "ACE": {
            "malaria-pilot": {
                "opp.yaml": """slug: malaria-pilot
display_name: Malaria Pilot — Northern Mozambique
created_at: 2026-03-15T09:00:00Z
created_by: neal@dimagi.com
labels:
  - malaria
  - mozambique
current_run_id: 2026-04-06-002
""",
                "idd.md": MALARIA_PILOT_IDD,
                "runs": {
                    "2026-04-01-001": {
                        "run.yaml": """run_id: 2026-04-01-001
mode: review
status: complete
started_at: 2026-04-01T10:00:00Z
completed_at: 2026-04-01T12:00:00Z
current_phase: closeout
current_step: cycle-grade
skill_versions:
  idea-to-idd: 4f2b8c1
  idd-to-learn-app: 4f2b8c1
""",
                        "events.jsonl": '{"ts":"2026-04-01T10:00:00Z","kind":"run.started"}\n',
                        "steps": {
                            "01-idea-to-idd": {
                                "step.yaml": _step_yaml("idea-to-idd", "app-building", 1),
                                "judge.yaml": _judge_yaml(7.8, "acceptable"),
                                "output": {"idd.md": MALARIA_PILOT_IDD},
                            },
                            "02-idd-to-learn-app": {
                                "step.yaml": _step_yaml("idd-to-learn-app", "app-building", 2),
                                "judge.yaml": _judge_yaml(7.1, "missing some forms"),
                                "output": {"learn-app-brief.md": "# Learn App Brief\n\n8 forms"},
                            },
                        },
                    },
                    "2026-04-06-002": {
                        "run.yaml": """run_id: 2026-04-06-002
mode: review
status: running
started_at: 2026-04-06T10:00:00Z
current_phase: app-building
current_step: app-deploy
skill_versions:
  idea-to-idd: 4f2b8c1
  idd-to-learn-app: 4f2b8c1
  app-deploy: 8a91f22
""",
                        "events.jsonl": '{"ts":"2026-04-06T10:00:00Z","kind":"run.started"}\n',
                        "steps": {
                            "01-idea-to-idd": {
                                "step.yaml": _step_yaml("idea-to-idd", "app-building", 1),
                                "judge.yaml": _judge_yaml(9.2, "comprehensive"),
                                "output": {"idd.md": MALARIA_PILOT_IDD},
                            },
                            "02-idd-to-learn-app": {
                                "step.yaml": _step_yaml("idd-to-learn-app", "app-building", 2),
                                "judge.yaml": _judge_yaml(8.5, "better now"),
                                "output": {"learn-app-brief.md": "# Learn App Brief\n\n12 forms"},
                            },
                            "03-idd-to-deliver-app": {
                                "step.yaml": _step_yaml("idd-to-deliver-app", "app-building", 3),
                                "judge.yaml": _judge_yaml(8.1),
                                "output": {"deliver-app-brief.md": "# Deliver App\n\n4 workflows"},
                            },
                            "04-app-deploy": {
                                "step.yaml": _step_yaml(
                                    "app-deploy", "app-building", 4, status="gate-pending"
                                ),
                                "gates.jsonl": (
                                    '{"ts":"2026-04-06T10:34:00Z","decision":"pending"}\n'
                                ),
                                "output": {
                                    "deploy-summary.md": "2 apps packaged\nawaiting publish"
                                },
                            },
                        },
                    },
                },
            }
        }
    }
