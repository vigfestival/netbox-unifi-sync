"""Unit tests for scheduler job-maintenance helpers (no NetBox/DB required)."""
from contextlib import nullcontext
from datetime import datetime, timezone as dt_timezone
from unittest.mock import MagicMock, patch

from netbox_unifi_sync.services import job_maintenance as jm


class TestDeleteIds:
    def test_empty_is_noop(self):
        with patch.object(jm, "_job_model") as job_model:
            assert jm._delete_ids([], batch_size=100) == 0
            job_model.assert_not_called()

    def test_batches_by_size_and_counts_total(self):
        Job = MagicMock()
        # _raw_delete returns the number of rows it deleted; emulate that from the
        # pk__in chunk size so the function's running total can be verified.
        def fake_raw_delete(_db):
            chunk = Job.objects.filter.call_args.kwargs["pk__in"]
            return len(chunk)
        Job.objects.filter.return_value._raw_delete.side_effect = fake_raw_delete
        with patch.object(jm, "_job_model", return_value=Job), \
             patch.object(jm.transaction, "atomic", lambda: nullcontext()):
            total = jm._delete_ids(list(range(250)), batch_size=100)
        assert total == 250
        # 250 ids / 100 per batch -> 3 batches (100, 100, 50)
        assert [len(c.kwargs["pk__in"]) for c in Job.objects.filter.call_args_list] == [100, 100, 50]


class TestPruneAfterTick:
    def test_excludes_enqueued_and_passes_retention(self):
        with patch.object(jm, "purge_scheduler_jobs", return_value={"ok": True}) as purge:
            out = jm.prune_scheduler_jobs_after_tick(keep_completed=200)
        assert out == {"ok": True}
        kwargs = purge.call_args.kwargs
        assert kwargs["include_enqueued"] is False
        assert kwargs["dry_run"] is False
        assert kwargs["keep_completed"] == 200

    def test_never_raises(self):
        with patch.object(jm, "purge_scheduler_jobs", side_effect=RuntimeError("boom")):
            # Must swallow the error so housekeeping can never break the sync.
            assert jm.prune_scheduler_jobs_after_tick() is None


class TestPurgeDryRun:
    def _fake_status(self):
        status = MagicMock()
        status.STATUS_SCHEDULED = "scheduled"
        status.STATUS_PENDING = "pending"
        status.STATUS_RUNNING = "running"
        status.TERMINAL_STATE_CHOICES = ("completed", "errored", "failed")
        return status

    def test_dry_run_counts_without_deleting(self):
        Job = MagicMock()
        # Every queryset built from base.filter(...)/.exclude(...) reports 5 rows.
        base = Job.objects.filter.return_value
        base.filter.return_value.count.return_value = 5
        base.filter.return_value.exclude.return_value.count.return_value = 5

        fixed_now = datetime(2026, 6, 25, 12, 0, tzinfo=dt_timezone.utc)
        with patch.object(jm, "_job_model", return_value=Job), \
             patch.object(jm, "_status_choices", return_value=self._fake_status()), \
             patch.object(jm.timezone, "now", return_value=fixed_now):
            summary = jm.purge_scheduler_jobs(dry_run=True, keep_completed=0)

        assert summary["dry_run"] is True
        assert summary["deleted"] == 0
        # enqueued + zombie_running + history all counted (5 each).
        assert summary["would_delete"] == summary["enqueued"] + summary["zombie_running"] + summary["history"]
        # Nothing was actually deleted.
        base.filter.return_value.delete.assert_not_called()
        base.filter.return_value.exclude.return_value.delete.assert_not_called()
