from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, render

from .filters import LEVELS, FilterError, filter_logs
from .models import LogEvent, Service

PAGE_SIZE = 50


def explorer(request):
    """Search/filter logs with server-side pagination."""
    error = None
    queryset = LogEvent.objects.select_related("service", "host")
    try:
        queryset = filter_logs(queryset, request.GET)
    except FilterError as exc:
        error, queryset = str(exc), LogEvent.objects.none()

    page_obj = Paginator(queryset.order_by("-timestamp", "-id"), PAGE_SIZE).get_page(request.GET.get("page"))
    query = request.GET.copy()
    query.pop("page", None)
    return render(request, "logs/explorer.html", {
        "page_obj": page_obj,
        "params": request.GET,
        "query": query.urlencode(),
        "error": error,
        "levels": LEVELS,
        "services": Service.objects.values_list("name", flat=True),
    })


def detail(request, pk):
    event = get_object_or_404(LogEvent.objects.select_related("service", "host", "pipeline_run"), pk=pk)
    return render(request, "logs/detail.html", {"event": event})
