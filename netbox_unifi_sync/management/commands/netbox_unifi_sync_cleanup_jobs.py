from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from netbox_unifi_sync.services.job_maintenance import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_RUNNING_GRACE_MINUTES,
    purge_scheduler_jobs,
    reschedule_scheduler,
)


class Command(BaseCommand):
    help = (
        "Clean up stale 'UniFi Sync Scheduler' background jobs and re-register the "
        "periodic schedule. Use this to recover automatic sync after the core_job "
        "table has filled with orphaned scheduled/zombie rows."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be deleted without changing anything.",
        )
        parser.add_argument(
            "--keep-completed",
            type=int,
            default=0,
            help="Number of most-recent terminal (completed/errored/failed) scheduler "
            "jobs to keep. Default 0 (delete all history).",
        )
        parser.add_argument(
            "--running-grace-minutes",
            type=int,
            default=DEFAULT_RUNNING_GRACE_MINUTES,
            help="Treat 'running' scheduler jobs older than this as dead zombies and "
            f"delete them. Default {DEFAULT_RUNNING_GRACE_MINUTES}.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=DEFAULT_BATCH_SIZE,
            help=f"Rows deleted per transaction. Default {DEFAULT_BATCH_SIZE}.",
        )
        parser.add_argument(
            "--no-reschedule",
            action="store_true",
            help="Do not re-register the periodic scheduler after cleanup. "
            "(A worker restart would re-register it on next startup.)",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            help="Emit the result summary as JSON.",
        )

    def handle(self, *args, **options):
        dry_run = bool(options.get("dry_run"))

        summary = purge_scheduler_jobs(
            keep_completed=max(0, int(options.get("keep_completed") or 0)),
            running_grace_minutes=int(options.get("running_grace_minutes")),
            batch_size=max(1, int(options.get("batch_size"))),
            include_enqueued=True,
            dry_run=dry_run,
        )

        rescheduled = None
        if not dry_run and not options.get("no_reschedule"):
            rescheduled = reschedule_scheduler()
        summary["rescheduled"] = rescheduled

        if options.get("json"):
            self.stdout.write(json.dumps(summary, indent=2, sort_keys=True, default=str))
            return

        verb = "Would delete" if dry_run else "Deleted"
        self.stdout.write(
            f"{verb}: enqueued(orphaned)={summary['enqueued']} "
            f"zombie_running={summary['zombie_running']} history={summary['history']}"
        )
        if not dry_run:
            self.stdout.write(self.style.SUCCESS(f"Total rows deleted: {summary['deleted']}"))
            if rescheduled and rescheduled.get("job_id"):
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Re-registered scheduler job #{rescheduled['job_id']} "
                        f"(scheduled={rescheduled.get('scheduled')}, "
                        f"interval={rescheduled.get('interval')} min)."
                    )
                )
            elif not options.get("no_reschedule"):
                self.stdout.write(
                    self.style.WARNING(
                        "Scheduler re-registration returned no job; check the worker "
                        "(it must run with --with-scheduler, which NetBox enables by default)."
                    )
                )
        else:
            self.stdout.write(
                f"Total that would be deleted: {summary.get('would_delete', 0)} (dry-run, no changes made)"
            )
