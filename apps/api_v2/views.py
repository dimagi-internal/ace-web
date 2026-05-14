"""Static docs UI views — Scalar (primary) and Redoc (reference)."""
from __future__ import annotations

from django.http import HttpRequest, HttpResponse

_SCALAR_HTML = """<!doctype html>
<html>
<head>
  <title>ace-web API — Scalar</title>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
</head>
<body>
  <script id="api-reference" data-url="/api/openapi.json"></script>
  <script>
    var configuration = {
      theme: "default",
      layout: "modern",
      hideDownloadButton: false,
      searchHotKey: "k",
    };
    document.getElementById("api-reference").dataset.configuration =
      JSON.stringify(configuration);
  </script>
  <script src="https://cdn.jsdelivr.net/npm/@scalar/api-reference"></script>
</body>
</html>
"""

_REDOC_HTML = """<!doctype html>
<html>
<head>
  <title>ace-web API — Redoc</title>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <style>body { margin: 0; padding: 0; }</style>
</head>
<body>
  <redoc spec-url="/api/openapi.json"></redoc>
  <script src="https://cdn.jsdelivr.net/npm/redoc/bundles/redoc.standalone.js"></script>
</body>
</html>
"""


def scalar_docs(request: HttpRequest) -> HttpResponse:
    return HttpResponse(_SCALAR_HTML, content_type="text/html; charset=utf-8")


def redoc_docs(request: HttpRequest) -> HttpResponse:
    return HttpResponse(_REDOC_HTML, content_type="text/html; charset=utf-8")
