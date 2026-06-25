"""Maintenance helpers for the plugin's NetBox background (``core.Job``) records.

Background
----------
The periodic sync is driven by ``UnifiSyncSchedulerJob``, registered with
NetBox's ``@system_job`` decorator. NetBox (re)schedules system jobs through
``JobRunner.enqueue_once()``, which is idempotent: at worker startup it looks
for an *already enqueued* job of the same class and, if one exists, returns it
without creating a new RQ schedule.

A historical NetBox job-reschedule race (upstream #22232) could create huge
numbers of duplicate ``"UniFi Sync Scheduler"`` ``core_job`` rows. Once a pile
of orphaned ``scheduled``/``pending`` rows exists in the database — rows that
are *not* backed by a live entry in the Redis scheduler — ``enqueue_once()``
keeps finding one of them and never registers a working schedule again. The
result is that automatic sync silently stops while the ``core_job`` table grows
without bound.

This module lets the plugin clean up after that situation **from within the
plugin** (a management command and a light self-prune on every scheduler tick),
instead of relying on manual database surgery.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Callable

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

logger = logging.getLogger("netbox.plugins.netbox_unifi_sync.maintenance")

# Must match ``UnifiSyncSchedulerJob.Meta.name``.
SCHEDULER_JOB_NAME = "UniFi Sync Scheduler"

# Sensible defaults shared by the management command and the per-tick prune.
DEFAULT_BATCH_SIZE = 20_000
DEFAULT_RUNNING_GRACE_MINUTES = 180


def _job_model():
    from core.models import Job

    return Job


def _status_choices():
    from core.choices import JobStatusChoices

    return JobStatusChoices


def _delete_ids(ids: list[int], batch_size: int) -> int:
    """Delete the given ``core_job`` ids in primary-key batches.

    Ids are collected once by the caller (a single sequential scan per
    category) and then deleted in chunks via the primary-key index, which
    keeps the work cheap even when millions of rows are involved.
    """
    if not ids:
        return 0

    Job = _job_model()
    deleted = 0
    for start in range(0, len(ids), batch_size):
        chunk = ids[start:start + batch_size]
        with transaction.atomic():
            Job.objects.filter(pk__in=chunk).delete()
        deleted += len(chunk)
    return deleted


def _collect_ids(queryset) -> list[int]:
    return list(queryset.values_list("id", flat=True))


def purge_scheduler_jobs(
    *,
    keep_completed: int = 0,
    running_grace_minutes: int = DEFAULT_RUNNING_GRACE_MINUTES,
    batch_size: int = DEFAULT_BATCH_SIZE,
    include_enqueued: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Remove stale ``"UniFi Sync Scheduler"`` ``core_job`` rows.

    Three independent categories are handled:

    * **enqueued** — ``scheduled``/``pending`` rows. When ``include_enqueued``
      is true these are removed so ``enqueue_once()`` can register a fresh,
      working schedule. The per-tick prune sets this to *false* so it never
      deletes the legitimately scheduled next run.
    * **zombie running** — ``running`` rows whose worker died long ago
      (``started`` — or ``created`` when never started — older than
      ``running_grace_minutes``). The currently executing tick is recent and is
      never matched.
    * **history** — terminal (``completed``/``errored``/``failed``) rows beyond
      the newest ``keep_completed`` to delete (``keep_completed=0`` removes all
      history).

    Only the plugin's own scheduler job name is ever touched. Returns a summary
    dict of per-category counts; with ``dry_run`` nothing is deleted.
    """
    Job = _job_model()
    status = _status_choices()
    now = timezone.now()
    cutoff = now - timedelta(minutes=max(0, int(running_grace_minutes)))

    base = Job.objects.filter(name=SCHEDULER_JOB_NAME)

    enqueued_qs = base.filter(
        status__in=(status.STATUS_SCHEDULED, status.STATUS_PENDING),
    )
    zombie_qs = base.filter(
        Q(started__lt=cutoff) | Q(started__isnull=True, created__lt=cutoff),
        status=status.STATUS_RUNNING,
    )

    keep_ids: list[int] = []
    if keep_completed > 0:
        keep_ids = list(
            base.filter(status__in=status.TERMINAL_STATE_CHOICES)
            .order_by("-created")
            .values_list("id", flat=True)[:keep_completed]
        )
    history_qs = base.filter(status__in=status.TERMINAL_STATE_CHOICES).exclude(
        id__in=keep_ids
    )

    summary: dict[str, Any] = {
        "dry_run": bool(dry_run),
        "include_enqueued": bool(include_enqueued),
        "keep_completed": int(keep_completed),
        "enqueued": enqueued_qs.count() if include_enqueued else 0,
        "zombie_running": zombie_qs.count(),
        "history": history_qs.count(),
        "deleted": 0,
    }

    if dry_run:
        summary["would_delete"] = (
            summary["enqueued"] + summary["zombie_running"] + summary["history"]
        )
        return summary

    deleted = 0
    if include_enqueued:
        deleted += _delete_ids(_collect_ids(enqueued_qs), batch_size)
    deleted += _delete_ids(_collect_ids(zombie_qs), batch_size)
    deleted += _delete_ids(_collect_ids(history_qs), batch_size)
    summary["deleted"] = deleted
    return summary


def reschedule_scheduler() -> dict[str, Any]:
    """Re-register the periodic scheduler job via NetBox's ``enqueue_once``.

    Safe to call while workers are running: ``enqueue_once`` is idempotent and
    pushes a fresh entry into the Redis scheduler that the running worker (which
    runs with ``--with-scheduler``) will pick up. Returns details of the
    resulting job.
    """
    from netbox.registry import registry

    from netbox_unifi_sync.jobs import UnifiSyncSchedulerJob

    kwargs = registry.get("system_jobs", {}).get(UnifiSyncSchedulerJob) or {"interval": 60}
    job = UnifiSyncSchedulerJob.enqueue_once(**kwargs)
    return {
        "job_id": getattr(job, "pk", None),
        "status": getattr(job, "status", None),
        "scheduled": getattr(job, "scheduled", None),
        "interval": getattr(job, "interval", None),
    }


def prune_scheduler_jobs_after_tick(
    *,
    keep_completed: int = 200,
    running_grace_minutes: int = DEFAULT_RUNNING_GRACE_MINUTES,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> dict[str, Any] | None:
    """Light, self-contained prune run on every scheduler tick.

    Trims terminal history and clears long-dead zombies so the ``core_job``
    table cannot slowly re-bloat. It deliberately leaves ``scheduled``/
    ``pending`` rows alone (``include_enqueued=False``) so the next scheduled
    run is never removed. Never raises — failures are logged and swallowed so
    housekeeping can never break the sync.
    """
    try:
        return purge_scheduler_jobs(
            keep_completed=keep_completed,
            running_grace_minutes=running_grace_minutes,
            batch_size=batch_size,
            include_enqueued=False,
            dry_run=False,
        )
    except Exception:  # pragma: no cover - defensive
        logger.exception("Scheduler job prune failed")
        return None
