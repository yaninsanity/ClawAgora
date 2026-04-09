"""Scan active capability bundles for missing integrity pins (SHA-256 / source URL)."""

from __future__ import annotations

import json

from django.conf import settings
from django.core.management.base import BaseCommand

from orchestration.models import CapabilityBundle


class Command(BaseCommand):
    help = (
        "List active capability bundles that violate CLAWAGORA_CAPABILITY_REQUIRE_* rules. "
        "Use --deactivate to soft-disable offending rows."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--deactivate",
            action="store_true",
            help="Set is_active=False on offending bundles.",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            help="Print machine-readable JSON to stdout.",
        )

    def handle(self, *args, **options):
        require_sha = bool(getattr(settings, "CLAWAGORA_CAPABILITY_REQUIRE_SHA256", False))
        require_url = bool(getattr(settings, "CLAWAGORA_CAPABILITY_REQUIRE_SOURCE_URL", False))
        deactivate: bool = options["deactivate"]
        as_json: bool = options["json"]

        offenders: list[dict] = []
        for b in CapabilityBundle.objects.filter(is_active=True).order_by("slug"):
            reasons: list[str] = []
            if require_url and not (b.source_url or "").strip():
                reasons.append("missing_source_url")
            if require_sha and len((b.source_sha256 or "").strip()) != 64:
                reasons.append("missing_or_invalid_sha256")
            if reasons:
                offenders.append(
                    {
                        "id": str(b.id),
                        "slug": b.slug,
                        "reasons": reasons,
                    }
                )

        if as_json:
            self.stdout.write(
                json.dumps(
                    {
                        "require_sha256": require_sha,
                        "require_source_url": require_url,
                        "offender_count": len(offenders),
                        "offenders": offenders,
                    },
                    indent=2,
                )
            )
            return

        self.stdout.write(
            f"require_sha256={require_sha} require_source_url={require_url} offenders={len(offenders)}"
        )
        for row in offenders:
            self.stdout.write(f"  {row['slug']}: {', '.join(row['reasons'])}")

        if deactivate and offenders:
            ids = [o["id"] for o in offenders]
            n = CapabilityBundle.objects.filter(id__in=ids, is_active=True).update(is_active=False)
            self.stdout.write(self.style.WARNING(f"Deactivated {n} bundle(s)."))
