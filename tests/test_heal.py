import json
from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone

from orchestration.models import Task
from orchestration.recovery import heal_stale_tasks


@pytest.mark.django_db
@override_settings(
    CLAWAGORA_HEAL_ENABLED=True,
    CLAWAGORA_STALE_RUNNING_SECONDS=120,
)
def test_heal_marks_stale_running():
    task = Task.objects.create(
        input_text="stale running probe",
        metadata={},
        status=Task.Status.RUNNING,
    )
    Task.objects.filter(pk=task.pk).update(
        updated_at=timezone.now() - timedelta(minutes=10),
    )

    result = heal_stale_tasks(dry_run=False)
    assert result.running_marked_failed >= 1
    assert str(task.id) in result.task_ids_running

    task.refresh_from_db()
    assert task.status == Task.Status.FAILED
    assert task.error_code == "stale_running_timeout"


@pytest.mark.django_db
@override_settings(
    CLAWAGORA_HEAL_ENABLED=True,
    CLAWAGORA_STALE_RUNNING_SECONDS=120,
)
def test_heal_dry_run_does_not_mutate():
    task = Task.objects.create(
        input_text="dry",
        metadata={},
        status=Task.Status.RUNNING,
    )
    Task.objects.filter(pk=task.pk).update(
        updated_at=timezone.now() - timedelta(minutes=30),
    )
    heal_stale_tasks(dry_run=True)
    task.refresh_from_db()
    assert task.status == Task.Status.RUNNING


@pytest.mark.django_db
@override_settings(CLAWAGORA_HEAL_ENABLED=False)
def test_heal_disabled_is_noop():
    task = Task.objects.create(
        input_text="v",
        metadata={},
        status=Task.Status.RUNNING,
    )
    Task.objects.filter(pk=task.pk).update(
        updated_at=timezone.now() - timedelta(days=1),
    )
    r = heal_stale_tasks(dry_run=False)
    assert r.running_marked_failed == 0
    task.refresh_from_db()
    assert task.status == Task.Status.RUNNING


@pytest.mark.django_db
@override_settings(
    CLAWAGORA_HEAL_ENABLED=True,
    CLAWAGORA_HEAL_REQUEUE_STALE_QUEUED=False,
    CLAWAGORA_STALE_QUEUED_SECONDS=120,
)
def test_heal_marks_stale_queued():
    task = Task.objects.create(
        input_text="stale queued probe",
        metadata={},
        status=Task.Status.QUEUED,
    )
    Task.objects.filter(pk=task.pk).update(
        updated_at=timezone.now() - timedelta(minutes=10),
    )

    result = heal_stale_tasks(dry_run=False)
    assert result.queued_marked_failed >= 1
    assert str(task.id) in result.task_ids_queued_failed

    task.refresh_from_db()
    assert task.status == Task.Status.FAILED
    assert task.error_code == "stale_queued_timeout"


@pytest.mark.django_db
@override_settings(CLAWAGORA_HEAL_ENABLED=True)
def test_clawagora_heal_json_flag():
    buf = StringIO()
    call_command("clawagora_heal", dry_run=True, json=True, stdout=buf)
    payload = json.loads(buf.getvalue().strip())
    assert payload["dry_run"] is True
