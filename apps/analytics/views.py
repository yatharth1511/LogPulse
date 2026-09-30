from django.shortcuts import render

from apps.logs.filters import RANGE_CHOICES, filter_logs, resolve_time_window
from apps.logs.models import LogEvent

from . import services


def dashboard(request):
    selected = request.GET.get("range", "all")
    if selected not in dict(RANGE_CHOICES):
        selected = "all"
    params = {"range": selected}
    queryset = filter_logs(LogEvent.objects.all(), params)
    start, end = resolve_time_window(params)
    data = services.build_report(queryset, start, end)

    chart_data = {
        "bucket": data["logs_over_time"]["bucket"],
        "time": data["logs_over_time"]["points"],
        "services": data["by_service"],
        "status_classes": data["status_distribution"]["classes"],
    }
    return render(request, "analytics/dashboard.html", {
        "data": data,
        "chart_data": chart_data,
        "recent_errors": services.recent_errors(queryset),
        "range_choices": RANGE_CHOICES,
        "selected_range": selected,
    })
