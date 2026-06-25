from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


class Command(BaseCommand):
    help = (
        "Consolidate the legacy 'Ubiquity Networks' manufacturer (slug 'ubiquity') "
        "into the canonical 'Ubiquiti' (slug 'ubiquiti'). For each legacy device "
        "type: if the target already has a type with the same model or slug, move "
        "the devices onto it and delete the legacy type (merge); otherwise just "
        "reassign the legacy type to the target manufacturer. Dry run by default."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--commit",
            action="store_true",
            help="Apply the changes. Without this flag the command only reports.",
        )
        parser.add_argument("--source-slug", default="ubiquity")
        parser.add_argument("--target-slug", default="ubiquiti")
        parser.add_argument(
            "--delete-empty-source",
            action="store_true",
            help="Delete the source manufacturer if it has no device types left.",
        )
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options):
        from dcim.models import Device, DeviceType, Manufacturer

        commit = bool(options.get("commit"))
        src = Manufacturer.objects.filter(slug=options["source_slug"]).first()
        tgt = Manufacturer.objects.filter(slug=options["target_slug"]).first()
        if not src:
            self.stdout.write("Source manufacturer not found; nothing to consolidate.")
            return
        if not tgt:
            raise CommandError(f"Target manufacturer slug '{options['target_slug']}' not found.")
        if src.id == tgt.id:
            raise CommandError("Source and target manufacturers are the same.")

        target_by_model = {dt.model: dt for dt in DeviceType.objects.filter(manufacturer=tgt)}
        target_by_slug = {dt.slug: dt for dt in DeviceType.objects.filter(manufacturer=tgt)}

        summary = {
            "commit": commit,
            "source": src.name,
            "target": tgt.name,
            "reassigned": 0,
            "merged": 0,
            "devices_moved": 0,
            "types_deleted": 0,
            "source_manufacturer_deleted": False,
        }
        actions: list[str] = []

        for dt in DeviceType.objects.filter(manufacturer=src).order_by("model"):
            ndev = Device.objects.filter(device_type=dt).count()
            merge_target = target_by_model.get(dt.model) or target_by_slug.get(dt.slug)
            if merge_target is not None:
                actions.append(
                    f"MERGE  {dt.model!r} ({ndev} dev) -> #{merge_target.id} {merge_target.model!r}"
                )
                summary["merged"] += 1
                summary["devices_moved"] += ndev
                summary["types_deleted"] += 1
                if commit:
                    with transaction.atomic():
                        Device.objects.filter(device_type=dt).update(device_type=merge_target)
                        dt.delete()
            else:
                actions.append(f"REASSIGN {dt.model!r} ({ndev} dev) -> {tgt.name!r}")
                summary["reassigned"] += 1
                if commit:
                    with transaction.atomic():
                        dt.manufacturer = tgt
                        dt.save(update_fields=["manufacturer"])
                # Reflect the move so a later same-model/slug legacy type merges into it.
                target_by_model[dt.model] = dt
                target_by_slug[dt.slug] = dt

        if options.get("delete_empty_source") and commit:
            if not DeviceType.objects.filter(manufacturer=src).exists():
                src.delete()
                summary["source_manufacturer_deleted"] = True

        if options.get("json"):
            self.stdout.write(json.dumps(summary, indent=2, sort_keys=True))
            return

        for line in actions:
            self.stdout.write("  " + line)
        head = "Applied" if commit else "Would apply"
        self.stdout.write(
            f"{head}: reassign={summary['reassigned']} merge={summary['merged']} "
            f"(devices_moved={summary['devices_moved']}, types_deleted={summary['types_deleted']})"
        )
        if not commit:
            self.stdout.write(self.style.WARNING("Dry run — no changes made. Re-run with --commit to apply."))
        else:
            self.stdout.write(self.style.SUCCESS("Consolidation applied."))
