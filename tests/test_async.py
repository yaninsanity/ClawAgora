from unittest.mock import patch

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import Client

from orchestration.models import Task


@pytest.mark.django_db
def test_async_create_returns_202_and_calls_enqueue():
    c = Client()
    with patch("orchestration.views.enqueue_task_execution") as q:
        r = c.post(
            "/api/v1/tasks/",
            data={"input_text": "Hello async world.", "metadata": {}},
            content_type="application/json",
            HTTP_X_CLAWAGORA_EXECUTION="async",
        )
    assert r.status_code == 202
    payload = r.json()
    assert payload["status"] == "queued"
    assert q.called


@pytest.mark.django_db
def test_async_create_returns_503_when_enqueue_unavailable():
    c = Client()
    with patch(
        "orchestration.views.enqueue_task_execution",
        side_effect=ImproperlyConfigured("no queue"),
    ):
        r = c.post(
            "/api/v1/tasks/",
            data={"input_text": "Hello.", "metadata": {}},
            content_type="application/json",
            HTTP_X_CLAWAGORA_EXECUTION="async",
        )
    assert r.status_code == 503
    t = Task.objects.latest("created_at")
    assert t.status == "failed"
    assert t.error_code == "enqueue_failed"
