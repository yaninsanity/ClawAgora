import json

from django.core.management.base import BaseCommand

from orchestration.app_settings import governance_runtime_config
from orchestration.jobs import (
    deliver_governance_alerts_job,
    refresh_governance_snapshots_job,
    replay_governance_dead_letters_job,
)


class Command(BaseCommand):
    help = "Run governance delivery worker and/or snapshot refresh jobs."

    def add_arguments(self, parser):
        cfg = governance_runtime_config()
        parser.add_argument("--deliver-alerts", action="store_true")
        parser.add_argument("--refresh-snapshots", action="store_true")
        parser.add_argument("--replay-dead-letters", action="store_true")
        parser.add_argument("--limit", type=int, default=cfg.dead_letter_default_limit)
        parser.add_argument("--profile", type=str, default="")
        parser.add_argument("--event-type", type=str, default="")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options):
        run_alerts = bool(options["deliver_alerts"])
        run_snapshots = bool(options["refresh_snapshots"])
        run_replay = bool(options["replay_dead_letters"])
        if not run_alerts and not run_snapshots and not run_replay:
            run_alerts = True
            run_snapshots = True
        payload = {}
        if run_alerts:
            payload["alerts"] = deliver_governance_alerts_job()
        if run_snapshots:
            payload["snapshots_refreshed"] = refresh_governance_snapshots_job()
        if run_replay:
            payload["dead_letters"] = replay_governance_dead_letters_job(
                limit=max(options["limit"], 1),
                profile=(options["profile"] or "").strip().lower() or None,
                event_type=(options["event_type"] or "").strip().lower() or None,
                dry_run=bool(options["dry_run"]),
            )
        if bool(options["json"]):
            self.stdout.write(json.dumps(payload, ensure_ascii=False))
            return
        self.stdout.write(str(payload))
