import logging
import time

logger = logging.getLogger(__name__)

EXCLUDED_PREFIXES = (
    "/metrics",
    "/static/",
    "/media/",
    "/favicon.ico",
    "/admin/jsi18n/",
)


class AnalyticsLoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start_time = time.time()
        response = self.get_response(request)
        duration_ms = round((time.time() - start_time) * 1000, 2)

        path = request.path
        if any(path.startswith(prefix) for prefix in EXCLUDED_PREFIXES):
            return response

        try:
            self._log_visit(request, response, duration_ms)
        except Exception as e:
            logger.debug("Failed to record page visit log: %s", e)

        return response

    def _get_client_ip(self, request):
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            ip = x_forwarded_for.split(",")[0].strip()
        else:
            ip = request.META.get("REMOTE_ADDR")
        return ip or ""

    def _log_visit(self, request, response, duration_ms):
        from .models import PageVisitLog

        user = getattr(request, "user", None)
        authenticated_user = user if (user and user.is_authenticated) else None

        PageVisitLog.objects.create(
            path=request.path[:512],
            method=request.method[:10],
            ip_address=self._get_client_ip(request)[:64],
            user=authenticated_user,
            user_agent=request.META.get("HTTP_USER_AGENT", "")[:1000],
            referer=request.META.get("HTTP_REFERER", "")[:1000],
            status_code=response.status_code,
            response_time_ms=duration_ms,
        )
