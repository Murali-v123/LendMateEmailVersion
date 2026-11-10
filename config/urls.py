from django.contrib import admin
from django.urls import include, path
from django.http import JsonResponse


def health_check(request):
    """
    Health-check endpoint for Render and other load balancers.
    Verifies database connectivity. Returns 503 if DB is unreachable.
    """
    try:
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return JsonResponse({"status": "ok"})
    except Exception:
        return JsonResponse({"status": "db_unavailable"}, status=503)


urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("", include("core.urls")),
    path("lending/", include("lending.urls")),
    path("", include("notifications.urls")),
    path("health/", health_check, name="health_check"),
]
