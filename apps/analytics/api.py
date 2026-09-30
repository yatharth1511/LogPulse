from rest_framework.response import Response
from rest_framework.views import APIView

from apps.logs.filters import FilterError, filter_logs, resolve_time_window
from apps.logs.models import LogEvent
from apps.logs.serializers import LogEventSerializer

from . import services


class AnalyticsView(APIView):
    """GET /api/analytics/ - aggregate statistics.

    Accepts the same filters as /api/logs/ (range, start, end, level, service, host, status_code, endpoint, q).
    """

    def get(self, request):
        try:
            queryset = filter_logs(LogEvent.objects.all(), request.query_params)
            start, end = resolve_time_window(request.query_params)
        except FilterError as exc:
            return Response({"detail": str(exc)}, status=400)
        report = services.build_report(queryset, start, end)
        report["recent_errors"] = LogEventSerializer(services.recent_errors(queryset), many=True).data
        return Response(report)
