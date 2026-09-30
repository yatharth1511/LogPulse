from django.db.models import Count, Q
from rest_framework import viewsets
from rest_framework.exceptions import ValidationError

from .filters import FilterError, filter_logs
from .models import LogEvent, Service
from .serializers import LogEventSerializer, ServiceSerializer


class LogEventViewSet(viewsets.ReadOnlyModelViewSet):
    """GET /api/logs/ (filterable + paginated) and GET /api/logs/<id>/.

    Query params: range, start, end, level, service, host, status_code, endpoint, q, page.
    """

    serializer_class = LogEventSerializer

    def get_queryset(self):
        queryset = LogEvent.objects.select_related("service", "host")
        if self.action == "list":
            try:
                queryset = filter_logs(queryset, self.request.query_params)
            except FilterError as exc:
                raise ValidationError({"detail": str(exc)})
        return queryset.order_by("-timestamp", "-id")


class ServiceViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ServiceSerializer

    def get_queryset(self):
        return Service.objects.annotate(
            log_count=Count("events"),
            error_count=Count("events", filter=Q(events__level__in=["ERROR", "CRITICAL"])),
        ).order_by("name")
