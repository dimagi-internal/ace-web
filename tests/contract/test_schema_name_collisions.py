"""No two response schemas may share an OpenAPI component name.

django-ninja names a component after the Python class's bare ``__name__``,
so two same-named classes in different apps collapse into ONE entry — and
the loser's endpoints get documented with the winner's shape, silently.

This is not hypothetical. ``apps/system/schemas.ArtifactOut`` (a manifest
row: path/description/required/...) and ``apps/opps/schemas.ArtifactOut``
(a step artifact: id/name/url/...) collided; the system one won, so
``StepSnapshotOut.artifacts`` was published with a shape that endpoint
never returns. The frontend was written against the published schema,
read ``drive_file_id`` off a payload that only carries ``id``, and the
Workbench artifact pane rendered "Couldn't load this artifact" for every
artifact on every step. Regenerating types could not catch it — the
generated types were themselves the wrong object.
"""
from collections import defaultdict


def _schema() -> dict:
    from apps.api.api import api as ninja_api

    return ninja_api.get_openapi_schema()


def test_no_two_python_classes_share_a_component_name():
    """The structural guard: one component name → one defining class."""
    from pydantic import BaseModel

    # Render the document first so every schema module is imported and its
    # classes are present in the subclass graph.
    published = set(_schema().get("components", {}).get("schemas", {}))

    by_name: dict[str, set[str]] = defaultdict(set)

    def walk(cls):
        for sub in cls.__subclasses__():
            if sub.__module__.startswith("apps."):
                by_name[sub.__name__].add(f"{sub.__module__}.{sub.__qualname__}")
            walk(sub)

    walk(BaseModel)
    collisions = {
        name: sorted(paths)
        for name, paths in by_name.items()
        if name in published and len(paths) > 1
    }
    assert not collisions, (
        "These schema class names are defined more than once and are published "
        "as OpenAPI components — one silently overwrites the other:\n"
        + "\n".join(f"  {n}: {p}" for n, p in collisions.items())
    )


def test_step_detail_artifacts_are_published_with_the_shape_returned():
    """The specific contract the collision corrupted."""
    schemas = _schema()["components"]["schemas"]
    step = schemas["StepSnapshotOut"]
    ref = step["properties"]["artifacts"]["items"]["$ref"].rsplit("/", 1)[-1]
    props = set(schemas[ref]["properties"])
    assert {"id", "name", "mime_type", "url", "is_text"} <= props, (
        f"step artifacts published as {ref} with {sorted(props)} — "
        "that is not the shape /steps/{skill} returns"
    )
    assert "produced_by" not in props, (
        f"{ref} is the artifact-MANIFEST shape; the step endpoint does not "
        "return it"
    )
