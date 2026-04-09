import json

from django.core.management.base import BaseCommand

from orchestration.recovery import heal_stale_tasks


class Command(BaseCommand):
    help = "Mark stale RUNNING/QUEUED tasks as failed or re-enqueue stale QUEUED (parameterized via settings)."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print actions without updating the database or enqueueing jobs.",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            help="Emit a single JSON summary line to stdout.",
        )

    def handle(self, *args, **options):
        dry = bool(options["dry_run"])
        as_json = bool(options["json"])
        result = heal_stale_tasks(dry_run=dry)

        payload = {
            "dry_run": dry,
            "running_marked_failed": result.running_marked_failed,
            "queued_marked_failed": result.queued_marked_failed,
            "queued_re_enqueued": result.queued_re_enqueued,
            "pending_approval_expired": result.pending_approval_expired,
            "task_ids_running": result.task_ids_running,
            "task_ids_queued_failed": result.task_ids_queued_failed,
            "task_ids_queued_requeued": result.task_ids_queued_requeued,
            "task_ids_approval_expired": result.task_ids_approval_expired,
        }

        if as_json:
            self.stdout.write(json.dumps(payload, ensure_ascii=False))
            return

        self.stdout.write(f"dry_run={dry}")
        self.stdout.write(f"running_marked_failed={result.running_marked_failed}")
        self.stdout.write(f"queued_marked_failed={result.queued_marked_failed}")
        self.stdout.write(f"queued_re_enqueued={result.queued_re_enqueued}")
        self.stdout.write(f"pending_approval_expired={result.pending_approval_expired}")
        if result.task_ids_running:
            self.stdout.write(f"running_task_ids={result.task_ids_running}")
        if result.task_ids_queued_failed:
            self.stdout.write(f"queued_failed_task_ids={result.task_ids_queued_failed}")
        if result.task_ids_queued_requeued:
            self.stdout.write(f"queued_requeued_task_ids={result.task_ids_queued_requeued}")
        if result.task_ids_approval_expired:
            self.stdout.write(f"approval_expired_task_ids={result.task_ids_approval_expired}")
