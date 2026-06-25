from __future__ import annotations

import ipaddress as ipa
import json

from django.core.management.base import BaseCommand
from django.db import transaction


class Command(BaseCommand):
    help = (
        "Backfill VRF on UniFi IP addresses that sit in the global table but whose "
        "containing prefix lives in a VRF (e.g. client IPs created before VRF "
        "scoping). Each IP is moved into its longest-matching VRF prefix's VRF, "
        "skipping any move that would collide with an existing address in that VRF."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change without modifying anything.",
        )
        parser.add_argument(
            "--tag",
            default="unifi-client",
            help="Only consider IPs carrying this tag. Pass an empty string to "
            "consider all global IPs. Default: unifi-client.",
        )
        parser.add_argument("--json", action="store_true", help="Emit a JSON summary.")

    def handle(self, *args, **options):
        from ipam.models import IPAddress, Prefix

        dry_run = bool(options.get("dry_run"))
        tag_name = (options.get("tag") or "").strip()

        # Only VRF-scoped prefixes are migration targets.
        vrf_prefixes = []
        for pf in Prefix.objects.filter(vrf__isnull=False).select_related("vrf"):
            try:
                net = ipa.ip_network(str(pf.prefix), strict=False)
            except ValueError:
                continue
            vrf_prefixes.append((net, pf.vrf_id, pf.vrf.name))

        def best_target(address) -> tuple[int, str] | None:
            try:
                host = ipa.ip_interface(str(address)).ip
            except ValueError:
                return None
            best = None
            best_len = -1
            for net, vrf_id, vrf_name in vrf_prefixes:
                if host in net and net.prefixlen > best_len:
                    best = (vrf_id, vrf_name)
                    best_len = net.prefixlen
            return best

        qs = IPAddress.objects.filter(vrf__isnull=True)
        if tag_name:
            qs = qs.filter(tags__name=tag_name)

        summary = {
            "dry_run": dry_run,
            "tag": tag_name or None,
            "considered": 0,
            "moved": 0,
            "skipped_no_vrf_prefix": 0,
            "skipped_collision": 0,
        }
        moved_examples: list[str] = []

        for ip in qs.distinct().iterator():
            summary["considered"] += 1
            target = best_target(ip.address)
            if not target:
                summary["skipped_no_vrf_prefix"] += 1
                continue
            vrf_id, vrf_name = target
            if IPAddress.objects.filter(address=ip.address, vrf_id=vrf_id).exists():
                summary["skipped_collision"] += 1
                continue
            if not dry_run:
                try:
                    with transaction.atomic():
                        ip.vrf_id = vrf_id
                        ip.save(update_fields=["vrf"])
                except Exception as exc:  # collision lost a race, etc.
                    summary["skipped_collision"] += 1
                    self.stderr.write(f"Skipped {ip.address}: {exc}")
                    continue
            summary["moved"] += 1
            if len(moved_examples) < 15:
                moved_examples.append(f"{ip.address} -> VRF {vrf_name}")

        if options.get("json"):
            self.stdout.write(json.dumps(summary, indent=2, sort_keys=True))
            return

        verb = "Would move" if dry_run else "Moved"
        self.stdout.write(
            f"{verb} {summary['moved']} IP(s) into their prefix VRF "
            f"(considered={summary['considered']}, "
            f"no-VRF-prefix={summary['skipped_no_vrf_prefix']}, "
            f"collisions-skipped={summary['skipped_collision']})."
        )
        for line in moved_examples:
            self.stdout.write(f"  {line}")
        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run — no changes made."))
        else:
            self.stdout.write(self.style.SUCCESS("Done."))
