from __future__ import annotations

import json
from uuid import uuid4

from core.choices import ObjectChangeActionChoices
from core.models import ObjectChange
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.contenttypes.models import ContentType
from django.db.models import Q
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import (
    GlobalSyncSettingsForm,
    RunActionForm,
    RunFilterForm,
    SiteMappingForm,
    UnifiControllerForm,
)
from .jobs import enqueue_sync_job
from datetime import timedelta

from .models import (
    PluginAuditEvent,
    SchedulerState,
    SiteMapping,
    SyncRun,
    SyncRunStatus,
    UnifiController,
)
from .services.audit import record_event, sanitize_error
from .services.orchestrator import (
    get_or_create_global_settings,
    test_controller_connection,
)
from .services.sync_runs import mark_stale_sync_runs


def _can_queue_sync(user) -> bool:
    return user.has_perm("netbox_unifi_sync.run_sync") or user.has_perm(
        "netbox_unifi_sync.add_syncrun"
    )


def _can_test_controller(user) -> bool:
    return user.has_perm("netbox_unifi_sync.test_controller") or user.has_perm(
        "netbox_unifi_sync.change_unificontroller"
    )


def _record_object_change(request: HttpRequest, obj, action: str) -> None:
    if not hasattr(obj, "to_objectchange"):
        return
    request_id = getattr(request, "id", None) or uuid4()
    content_type = ContentType.objects.get_for_model(obj)
    if ObjectChange.objects.filter(
        changed_object_type=content_type,
        changed_object_id=obj.pk,
        request_id=request_id,
        action=action,
    ).exists():
        return
    objectchange = obj.to_objectchange(action)
    if not objectchange or not objectchange.has_changes:
        return
    objectchange.user = request.user
    objectchange.request_id = request_id
    objectchange.save()


@login_required
@permission_required("netbox_unifi_sync.view_syncrun", raise_exception=True)
def dashboard_view(request: HttpRequest) -> HttpResponse:
    settings_obj = get_or_create_global_settings()
    mark_stale_sync_runs()
    latest_run = SyncRun.objects.order_by("-created").first()
    recent_runs = SyncRun.objects.order_by("-created")[:10]

    form = RunActionForm(
        initial={
            "dry_run": settings_obj.dry_run_default,
            "cleanup": settings_obj.cleanup_enabled,
        }
    )
    if request.method == "POST":
        if not _can_queue_sync(request.user):
            return HttpResponseForbidden(
                "Missing permission: netbox_unifi_sync.run_sync or netbox_unifi_sync.add_syncrun"
            )
        form = RunActionForm(request.POST)
        if form.is_valid():
            # A dedicated "Dry run" submit button forces dry-run mode.
            dry_run = bool(form.cleaned_data.get("dry_run")) or "_dryrun" in request.POST
            cleanup = bool(form.cleaned_data.get("cleanup"))
            try:
                job = enqueue_sync_job(
                    user=request.user,
                    dry_run=dry_run,
                    cleanup_requested=cleanup,
                    trigger="plugin-ui",
                )
            except Exception as exc:
                safe = sanitize_error(str(exc))
                messages.error(request, f"Failed to queue sync job: {safe}")
                record_event(
                    action="sync.enqueue",
                    status="error",
                    actor=request.user,
                    message=safe,
                    details={"dry_run": dry_run, "cleanup": cleanup},
                )
            else:
                identifier = (
                    getattr(job, "id", None) or getattr(job, "pk", None) or "queued"
                )
                messages.success(request, f"Queued sync job ({identifier}).")
                record_event(
                    action="sync.enqueue",
                    status="success",
                    actor=request.user,
                    message="sync job queued",
                    details={
                        "dry_run": dry_run,
                        "cleanup": cleanup,
                        "job": str(identifier),
                    },
                )
            return redirect("plugins:netbox_unifi_sync:dashboard")

    controllers = list(UnifiController.objects.order_by("name"))
    enabled_controllers = [c for c in controllers if c.enabled]

    # UniFi API status: aggregate of the enabled controllers' last connection test.
    if not enabled_controllers:
        unifi_status, unifi_status_color = "No controllers", "gray"
    elif all(c.last_test_status == "ok" for c in enabled_controllers):
        unifi_status, unifi_status_color = "Reachable", "green"
    elif any(c.last_test_status == "error" for c in enabled_controllers):
        unifi_status, unifi_status_color = "Error", "red"
    else:
        unifi_status, unifi_status_color = "Unknown", "gray"

    # Next scheduled run (if scheduling is enabled).
    next_sync = None
    if settings_obj.enabled and settings_obj.schedule_enabled:
        state = SchedulerState.objects.filter(key="default").first()
        if state and state.last_auto_sync:
            next_sync = state.last_auto_sync + timedelta(minutes=settings_obj.sync_interval_minutes)
        else:
            next_sync = timezone.now()

    context = {
        "settings": settings_obj,
        "latest_run": latest_run,
        "recent_runs": recent_runs,
        "form": form,
        "controllers": controllers,
        "controller_count": len(enabled_controllers),
        "can_queue_sync": _can_queue_sync(request.user),
        # NetBox runs the plugin in-process, so the NetBox API is reachable
        # whenever this page renders.
        "netbox_status": "Reachable",
        "netbox_status_color": "green",
        "unifi_status": unifi_status,
        "unifi_status_color": unifi_status_color,
        "next_sync": next_sync,
    }
    return render(request, "netbox_unifi_sync/dashboard.html", context)


@login_required
@permission_required(
    "netbox_unifi_sync.change_globalsyncsettings", raise_exception=True
)
def settings_view(request: HttpRequest) -> HttpResponse:
    settings_obj = get_or_create_global_settings()
    form = GlobalSyncSettingsForm(instance=settings_obj)

    if request.method == "POST":
        settings_obj.snapshot()
        form = GlobalSyncSettingsForm(request.POST, instance=settings_obj)
        if form.is_valid():
            obj = form.save()
            _record_object_change(
                request,
                obj,
                ObjectChangeActionChoices.ACTION_UPDATE,
            )
            record_event(
                action="settings.update",
                status="success",
                actor=request.user,
                message="Global settings updated",
            )
            messages.success(request, "Global settings updated")
            return redirect("plugins:netbox_unifi_sync:settings")
        messages.error(request, "Unable to save settings. Fix validation errors.")

    return render(
        request,
        "netbox_unifi_sync/settings.html",
        {"form": form, "settings": settings_obj},
    )


@login_required
@permission_required("netbox_unifi_sync.view_unificontroller", raise_exception=True)
def controller_list_view(request: HttpRequest) -> HttpResponse:
    controllers = UnifiController.objects.order_by("name")
    return render(
        request, "netbox_unifi_sync/controllers.html", {"controllers": controllers}
    )


@login_required
@permission_required("netbox_unifi_sync.change_unificontroller", raise_exception=True)
def controller_edit_view(request: HttpRequest, pk: int | None = None) -> HttpResponse:
    controller = get_object_or_404(UnifiController, pk=pk) if pk else None
    form = UnifiControllerForm(instance=controller)

    if request.method == "POST":
        if controller:
            controller.snapshot()
        form = UnifiControllerForm(request.POST, instance=controller)
        if form.is_valid():
            obj = form.save()
            _record_object_change(
                request,
                obj,
                ObjectChangeActionChoices.ACTION_UPDATE if controller else ObjectChangeActionChoices.ACTION_CREATE,
            )
            action = "controller.update" if controller else "controller.create"
            record_event(
                action=action,
                status="success",
                actor=request.user,
                target=obj.name,
                message=f"{obj.name} saved",
            )
            messages.success(request, f"Controller '{obj.name}' saved")
            return redirect("plugins:netbox_unifi_sync:controllers")
        error_items: list[str] = []
        for field, field_errors in form.errors.items():
            label = "general" if field == "__all__" else field
            error_items.extend([f"{label}: {e}" for e in field_errors])
        details = " | ".join(error_items) if error_items else "Fix validation errors."
        messages.error(request, f"Unable to save controller. {details}")

    return render(
        request,
        "netbox_unifi_sync/controller_form.html",
        {"form": form, "controller": controller},
    )


@login_required
@permission_required("netbox_unifi_sync.delete_unificontroller", raise_exception=True)
def controller_delete_view(request: HttpRequest, pk: int) -> HttpResponse:
    controller = get_object_or_404(UnifiController, pk=pk)
    if request.method == "POST":
        name = controller.name
        controller.delete()
        messages.success(request, f"Controller '{name}' deleted")
        record_event(
            action="controller.delete",
            status="success",
            actor=request.user,
            target=name,
            message=f"{name} deleted",
        )
        return redirect("plugins:netbox_unifi_sync:controllers")
    return render(
        request, "netbox_unifi_sync/controller_delete.html", {"controller": controller}
    )


@login_required
@require_POST
def controller_test_view(request: HttpRequest, pk: int) -> HttpResponse:
    if not _can_test_controller(request.user):
        return HttpResponseForbidden(
            "Missing permission: netbox_unifi_sync.test_controller or netbox_unifi_sync.change_unificontroller"
        )
    controller = get_object_or_404(UnifiController, pk=pk)
    settings_obj = get_or_create_global_settings()
    try:
        result = test_controller_connection(controller, settings_obj)
        controller.last_tested = timezone.now()
        controller.last_test_status = "ok"
        controller.last_test_error = ""
        controller.save(
            update_fields=["last_test_status", "last_test_error", "last_tested"]
        )
        messages.success(
            request, f"Controller '{controller.name}' test OK. Sites: {result['sites']}"
        )
        record_event(
            action="controller.test",
            status="success",
            actor=request.user,
            target=controller.name,
            message="Controller test succeeded",
            details=result,
        )
    except Exception as exc:
        safe = sanitize_error(str(exc))
        controller.last_test_status = "error"
        controller.last_test_error = safe
        controller.last_tested = timezone.now()
        controller.save(
            update_fields=["last_test_status", "last_test_error", "last_tested"]
        )
        messages.error(request, f"Controller test failed: {safe}")
        record_event(
            action="controller.test",
            status="error",
            actor=request.user,
            target=controller.name,
            message=safe,
        )
    return redirect("plugins:netbox_unifi_sync:controllers")


@login_required
@require_POST
def controller_test_api_view(request: HttpRequest, pk: int) -> JsonResponse:
    if not _can_test_controller(request.user):
        return JsonResponse(
            {
                "status": "error",
                "error": "Missing permission: netbox_unifi_sync.test_controller or netbox_unifi_sync.change_unificontroller",
            },
            status=403,
        )
    controller = get_object_or_404(UnifiController, pk=pk)
    settings_obj = get_or_create_global_settings()
    try:
        result = test_controller_connection(controller, settings_obj)
        controller.last_test_status = "ok"
        controller.last_test_error = ""
        controller.last_tested = timezone.now()
        controller.save(
            update_fields=["last_test_status", "last_test_error", "last_tested"]
        )
        return JsonResponse(result, status=200)
    except Exception as exc:
        safe = sanitize_error(str(exc))
        controller.last_test_status = "error"
        controller.last_test_error = safe
        controller.last_tested = timezone.now()
        controller.save(
            update_fields=["last_test_status", "last_test_error", "last_tested"]
        )
        return JsonResponse({"status": "error", "error": safe}, status=400)


@login_required
@permission_required("netbox_unifi_sync.view_sitemapping", raise_exception=True)
def mapping_list_view(request: HttpRequest) -> HttpResponse:
    mappings = SiteMapping.objects.select_related("controller").order_by(
        "controller__name", "unifi_site"
    )
    return render(request, "netbox_unifi_sync/mappings.html", {"mappings": mappings})


@login_required
@permission_required("netbox_unifi_sync.change_sitemapping", raise_exception=True)
def mapping_edit_view(request: HttpRequest, pk: int | None = None) -> HttpResponse:
    mapping = get_object_or_404(SiteMapping, pk=pk) if pk else None
    form = SiteMappingForm(instance=mapping)
    if request.method == "POST":
        if mapping:
            mapping.snapshot()
        form = SiteMappingForm(request.POST, instance=mapping)
        if form.is_valid():
            row = form.save()
            _record_object_change(
                request,
                row,
                ObjectChangeActionChoices.ACTION_UPDATE if mapping else ObjectChangeActionChoices.ACTION_CREATE,
            )
            messages.success(request, "Site mapping saved")
            record_event(
                action="mapping.save",
                status="success",
                actor=request.user,
                target=str(row.pk),
                message="Site mapping saved",
            )
            return redirect("plugins:netbox_unifi_sync:mappings")
        messages.error(request, "Unable to save mapping. Fix validation errors.")
    return render(
        request,
        "netbox_unifi_sync/mapping_form.html",
        {"form": form, "mapping": mapping},
    )


@login_required
@permission_required("netbox_unifi_sync.delete_sitemapping", raise_exception=True)
def mapping_delete_view(request: HttpRequest, pk: int) -> HttpResponse:
    mapping = get_object_or_404(SiteMapping, pk=pk)
    if request.method == "POST":
        mapping.delete()
        messages.success(request, "Site mapping deleted")
        record_event(
            action="mapping.delete",
            status="success",
            actor=request.user,
            message="Site mapping deleted",
        )
        return redirect("plugins:netbox_unifi_sync:mappings")
    return render(
        request, "netbox_unifi_sync/mapping_delete.html", {"mapping": mapping}
    )


@login_required
@permission_required("netbox_unifi_sync.view_syncrun", raise_exception=True)
def run_list_view(request: HttpRequest) -> HttpResponse:
    mark_stale_sync_runs()
    queryset = SyncRun.objects.order_by("-created")
    form = RunFilterForm(request.GET)
    if form.is_valid():
        status = (form.cleaned_data.get("status") or "").strip()
        if status:
            queryset = queryset.filter(status=status)
        q = (form.cleaned_data.get("q") or "").strip()
        if q:
            queryset = queryset.filter(Q(summary__icontains=q) | Q(error__icontains=q))
        limit = form.cleaned_data.get("limit") or 100
    else:
        limit = 100

    runs = queryset[:limit]
    return render(
        request,
        "netbox_unifi_sync/runs.html",
        {"runs": runs, "form": form, "total": queryset.count()},
    )


@login_required
@permission_required("netbox_unifi_sync.view_syncrun", raise_exception=True)
def run_detail_view(request: HttpRequest, pk: int) -> HttpResponse:
    run = get_object_or_404(SyncRun, pk=pk)
    try:
        details_json = json.dumps(run.details or {}, indent=2, sort_keys=True, default=str)
    except (TypeError, ValueError):
        details_json = str(run.details)
    # Flatten the per-controller-group breakdown for a readable table.
    groups = []
    cleanup_effective = None
    inner = run.details.get("details", {}) if isinstance(run.details, dict) else {}
    if isinstance(inner, dict):
        cleanup_effective = inner.get("cleanup_effective")
        for grp in inner.get("groups", []) or []:
            result = grp.get("result", {}) if isinstance(grp, dict) else {}
            groups.append({
                "group": grp.get("group"),
                "controllers": ", ".join(grp.get("controllers", []) or []),
                "controllers_total": result.get("controllers"),
                "sites": result.get("sites"),
                "devices": result.get("devices"),
                "mode": result.get("mode"),
            })
    return render(
        request,
        "netbox_unifi_sync/run_detail.html",
        {
            "run": run,
            "details_json": details_json,
            "groups": groups,
            "cleanup_effective": cleanup_effective,
        },
    )


@login_required
@permission_required("netbox_unifi_sync.view_syncrun", raise_exception=True)
def run_status_view(request: HttpRequest, pk: int) -> JsonResponse:
    """Lightweight JSON status for a single run, used for live UI polling."""
    mark_stale_sync_runs()
    run = get_object_or_404(SyncRun, pk=pk)
    terminal = run.status in (
        SyncRunStatus.SUCCESS,
        SyncRunStatus.FAILED,
        SyncRunStatus.DRY_RUN,
        SyncRunStatus.SKIPPED,
    )
    if run.completed and run.started:
        elapsed_ms = int((run.completed - run.started).total_seconds() * 1000)
    elif run.started:
        elapsed_ms = int((timezone.now() - run.started).total_seconds() * 1000)
    else:
        elapsed_ms = 0
    return JsonResponse(
        {
            "id": run.pk,
            "status": run.status,
            "status_display": run.get_status_display(),
            "is_terminal": terminal,
            "started": run.started.isoformat() if run.started else None,
            "completed": run.completed.isoformat() if run.completed else None,
            "elapsed_ms": elapsed_ms,
            "duration_ms": run.duration_ms,
            "controllers": run.controllers_total,
            "sites": run.sites_total,
            "devices": run.devices_total,
            "summary": run.summary,
            "error": run.error,
        }
    )


@login_required
@permission_required("netbox_unifi_sync.view_pluginauditevent", raise_exception=True)
def audit_list_view(request: HttpRequest) -> HttpResponse:
    queryset = PluginAuditEvent.objects.select_related("actor").order_by("-created")
    status = (request.GET.get("status") or "").strip()
    if status in ("success", "error"):
        queryset = queryset.filter(status=status)
    q = (request.GET.get("q") or "").strip()
    if q:
        queryset = queryset.filter(
            Q(action__icontains=q) | Q(message__icontains=q) | Q(target__icontains=q)
        )
    total = queryset.count()
    events = queryset[:200]
    return render(
        request,
        "netbox_unifi_sync/audit.html",
        {"events": events, "total": total, "status": status, "q": q},
    )


@login_required
@permission_required("netbox_unifi_sync.view_syncrun", raise_exception=True)
def api_status_view(request: HttpRequest) -> JsonResponse:
    settings_obj = get_or_create_global_settings()
    mark_stale_sync_runs()
    latest = SyncRun.objects.order_by("-created").first()
    payload = {
        "enabled": settings_obj.enabled,
        "schedule_enabled": settings_obj.schedule_enabled,
        "sync_interval_minutes": settings_obj.sync_interval_minutes,
        "latest_run": None,
    }
    if latest:
        payload["latest_run"] = {
            "id": latest.pk,
            "status": latest.status,
            "created": latest.created.isoformat(),
            "completed": latest.completed.isoformat() if latest.completed else None,
            "summary": latest.summary,
            "controllers": latest.controllers_total,
            "sites": latest.sites_total,
            "devices": latest.devices_total,
        }
    return JsonResponse(payload)
