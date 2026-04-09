from __future__ import annotations

from pathlib import Path

from django.http import FileResponse, Http404
from django.views import View


class SpaFallbackView(View):
    def get(self, request, path="", document_root=None):
        root = Path(document_root or "")
        index = root / "index.html"
        if not index.is_file():
            raise Http404()
        if path:
            candidate = root / path
            try:
                candidate.resolve().relative_to(root.resolve())
            except ValueError:
                raise Http404()
            if candidate.is_file():
                fh = candidate.open("rb")
                return FileResponse(fh)
        fh = index.open("rb")
        return FileResponse(fh)
