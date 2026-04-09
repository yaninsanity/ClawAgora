import pytest

from orchestration.jobs import run_task_job
from orchestration.models import Task
from orchestration.services import get_orchestration_service


@pytest.mark.django_db
def test_worker_job_is_idempotent_after_completion():
    task = Task.objects.create(
        input_text="Worker idempotency check.",
        metadata={},
        status=Task.Status.RECEIVED,
    )
    get_orchestration_service().run_task(task)
    task.refresh_from_db()
    assert task.status == Task.Status.COMPLETED

    run_task_job(str(task.id))

    task.refresh_from_db()
    assert task.status == Task.Status.COMPLETED
