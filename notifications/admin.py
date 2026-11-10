from django.contrib import admin

from .models import EmailNotification


@admin.register(EmailNotification)
class EmailNotificationAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "notification_type",
        "borrower",
        "recipient_role",
        "recipient_email",
        "status",
        "attempts",
        "created_at",
        "sent_at",
    ]
    list_filter = ["status", "notification_type", "recipient_role", "created_at"]
    search_fields = [
        "borrower__full_name",
        "recipient_email",
        "subject",
        "event_key",
    ]
    readonly_fields = [
        "event_key",
        "provider_message_id",
        "created_at",
        "updated_at",
        "sent_at",
        "next_retry_at",
    ]
    raw_id_fields = ["borrower", "loan", "payment", "lender"]
    date_hierarchy = "created_at"
    ordering = ["-created_at"]

    def has_add_permission(self, request):
        # Notifications are created by the system, never by hand.
        return False

    def has_change_permission(self, request, obj=None):
        # Preserve the audit history.
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related("borrower", "loan", "lender")
        if request.user.is_superuser:
            return qs
        return qs.filter(lender=request.user)
