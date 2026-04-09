from django.urls import include, path, re_path
from django.views.static import serve
from pathlib import Path

from clawagora_server.spa import SpaFallbackView

urlpatterns = [
    path("api/", include("orchestration.urls")),
]

_web_dist = Path(__file__).resolve().parent.parent.parent.parent / "web" / "dist"
if _web_dist.is_dir():
    urlpatterns += [
        re_path(r"^assets/(?P<path>.*)$", serve, {"document_root": _web_dist / "assets"}),
        re_path(r"^(?P<path>.*)$", SpaFallbackView.as_view(), {"document_root": _web_dist}),
    ]
