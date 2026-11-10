from django.contrib import admin
from django.core.exceptions import ValidationError
from .models import Borrower, Loan, Payment, BorrowerTracker, TrackerItem, AuditEvent


@admin.register(Borrower)
class BorrowerAdmin(admin.ModelAdmin):
    list_display = (
        "full_name",
        "email",
        "lender",
        "email_consent",
        "created_at",
    )

    search_fields = (
        "full_name",
        "email",
    )

    list_filter = (
        "email_consent",
        "created_at",
    )

    readonly_fields = (
        "lender",
        "created_at",
    )

    def get_queryset(self, request):
        queryset = super().get_queryset(request)

        if request.user.is_superuser:
            return queryset

        return queryset.filter(lender=request.user)

    def save_model(self, request, obj, form, change):
        if not change:
            obj.lender = request.user

        super().save_model(request, obj, form, change)


@admin.register(Loan)
class LoanAdmin(admin.ModelAdmin):
    list_display = (
        "loan_id",
        "borrower",
        "principal",
        "interest_rate",
        "interest_period",
        "interest_basis",
        "lending_date",
        "due_date",
        "status",
        "closed_at",
    )

    search_fields = (
        "borrower__full_name",
        "loan_id",
    )

    list_filter = (
        "status",
        "interest_period",
        "interest_basis",
    )

    def has_add_permission(self, request):
        # Loan creation must go through create_loan() service for audit events.
        return False

    def get_readonly_fields(self, request, obj=None):
        if obj is None:
            return ["loan_id", "created_at", "updated_at", "closed_at"]
        # All financial and date fields are readonly for existing loans.
        # Edits must go through edit_loan() service for audit events.
        return [
            "loan_id",
            "borrower",
            "principal",
            "interest_rate",
            "interest_period",
            "interest_basis",
            "lending_date",
            "due_date",
            "monthly_due_day",
            "status",
            "closed_at",
            "created_at",
            "updated_at",
        ]

    def has_change_permission(self, request, obj=None):
        # Allow viewing loan detail in admin but all fields are readonly.
        return True

    def get_queryset(self, request):
        queryset = super().get_queryset(request).select_related(
            "borrower",
            "borrower__lender",
        )

        if request.user.is_superuser:
            return queryset

        return queryset.filter(borrower__lender=request.user)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "borrower" and not request.user.is_superuser:
            kwargs["queryset"] = Borrower.objects.filter(
                lender=request.user
            )

        return super().formfield_for_foreignkey(
            db_field, request, **kwargs
        )


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        "loan",
        "payment_date",
        "amount",
        "principal_component",
        "interest_component",
        "voided_at",
        "created_at",
    )
    list_filter = ("payment_date", "voided_at", "created_at")
    search_fields = ("loan__loan_id", "loan__borrower__full_name", "void_reason")

    def get_readonly_fields(self, request, obj=None):
        if obj:  # Direct editing of financial/status fields is disallowed
            return (
                "loan",
                "payment_date",
                "amount",
                "principal_component",
                "interest_component",
                "notes",
                "voided_at",
                "void_reason",
                "voided_by",
                "created_at",
                "updated_at",
            )
        return ("created_at", "updated_at", "voided_at", "voided_by")

    def get_queryset(self, request):
        queryset = super().get_queryset(request).select_related(
            "loan",
            "loan__borrower",
            "loan__borrower__lender",
        )
        if request.user.is_superuser:
            return queryset
        return queryset.filter(loan__borrower__lender=request.user)

    def has_delete_permission(self, request, obj=None):
        # Payments must never be hard-deleted via Django Admin
        return False

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "loan" and not request.user.is_superuser:
            kwargs["queryset"] = Loan.objects.filter(
                borrower__lender=request.user,
                status="open",
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


class TrackerItemInline(admin.TabularInline):
    model = TrackerItem
    extra = 1


@admin.register(BorrowerTracker)
class BorrowerTrackerAdmin(admin.ModelAdmin):
    list_display = ("title", "borrower", "tracker_type", "loan", "start_date", "end_date", "created_at")
    list_filter = ("tracker_type",)
    inlines = [TrackerItemInline]

    def get_queryset(self, request):
        queryset = super().get_queryset(request).select_related("borrower__lender")
        if request.user.is_superuser:
            return queryset
        return queryset.filter(borrower__lender=request.user)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if not request.user.is_superuser:
            if db_field.name == "borrower":
                kwargs["queryset"] = Borrower.objects.filter(lender=request.user)
            elif db_field.name == "loan":
                kwargs["queryset"] = Loan.objects.filter(borrower__lender=request.user)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(TrackerItem)
class TrackerItemAdmin(admin.ModelAdmin):
    list_display = ("title", "tracker", "tracking_date", "is_completed", "completed_at")
    list_filter = ("is_completed",)

    def get_queryset(self, request):
        queryset = super().get_queryset(request).select_related("tracker__borrower__lender")
        if request.user.is_superuser:
            return queryset
        return queryset.filter(tracker__borrower__lender=request.user)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "tracker" and not request.user.is_superuser:
            kwargs["queryset"] = BorrowerTracker.objects.filter(borrower__lender=request.user)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("event_type", "user", "loan", "payment", "created_at")
    list_filter = ("event_type", "created_at")
    search_fields = ("event_type", "loan__loan_id", "details", "reason")
    readonly_fields = ("user", "event_type", "loan", "payment", "details", "reason", "created_at")

    def get_queryset(self, request):
        queryset = super().get_queryset(request).select_related("loan__borrower__lender", "user")
        if request.user.is_superuser:
            return queryset
        return queryset.filter(loan__borrower__lender=request.user)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
