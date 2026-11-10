"""
Notification history views.

All queries are scoped to the authenticated lender.
No other lender's notifications are ever exposed.
"""
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import EmailNotification

logger = logging.getLogger(__name__)

NOTIFICATIONS_PER_PAGE = 25


@login_required
def notification_history(request):
    """Display paginated notification history for the logged-in lender."""
    status_filter = request.GET.get("status", "all").strip().lower()

    qs = (
        EmailNotification.objects
        .filter(lender=request.user)
        .select_related("borrower", "loan")
        .order_by("-created_at")
    )

    if status_filter in ("sent", "pending", "failed", "suppressed", "processing"):
        qs = qs.filter(status=status_filter)

    paginator = Paginator(qs, NOTIFICATIONS_PER_PAGE)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    # Counts for filter badges
    counts = {
        "all": EmailNotification.objects.filter(lender=request.user).count(),
        "sent": EmailNotification.objects.filter(lender=request.user, status="sent").count(),
        "pending": EmailNotification.objects.filter(lender=request.user, status="pending").count(),
        "failed": EmailNotification.objects.filter(lender=request.user, status="failed").count(),
        "suppressed": EmailNotification.objects.filter(lender=request.user, status="suppressed").count(),
    }

    context = {
        "page_obj": page_obj,
        "status_filter": status_filter,
        "counts": counts,
    }
    return render(request, "notifications/history.html", context)


@login_required
@require_POST
def retry_notification(request, pk):
    """
    Manually retry a failed notification.
    Only the owning lender can retry their own notifications.
    """
    notification = get_object_or_404(
        EmailNotification,
        pk=pk,
        lender=request.user,
    )

    if notification.status != EmailNotification.FAILED:
        messages.warning(
            request,
            f"Notification #{pk} is not in a failed state and cannot be retried."
        )
        return redirect("notifications:history")

    if notification.attempts >= 5:
        messages.error(
            request,
            f"Notification #{pk} has exhausted all retry attempts. Create a new notification if needed."
        )
        return redirect("notifications:history")

    # Reset for retry
    notification.status = EmailNotification.PENDING
    notification.last_error = ""
    notification.next_retry_at = None
    notification.save(update_fields=["status", "last_error", "next_retry_at"])

    try:
        from .tasks import send_email_notification  # noqa: PLC0415
        send_email_notification.delay(notification.pk)
        messages.success(request, f"Notification #{pk} has been queued for retry.")
    except Exception:  # noqa: BLE001
        messages.warning(
            request,
            f"Notification #{pk} reset to pending, but Celery may be unavailable. "
            "It will be processed when the worker recovers."
        )

    return redirect("notifications:history")
