from django.contrib import messages
from django.core.paginator import Paginator
from django.shortcuts import redirect, render

from apps.logs.models import PipelineRun

from .services import run_pipeline_for_upload


def pipelines(request):
    """Pipeline run history plus a simple upload form."""
    if request.method == "POST":
        upload = request.FILES.get("file")
        if upload is None:
            messages.error(request, "Choose a log file to upload.")
        else:
            try:
                run = run_pipeline_for_upload(
                    upload,
                    service=request.POST.get("service", "").strip() or None,
                    host=request.POST.get("host", "").strip() or None,
                )
            except Exception as exc:  # surface any failure to the user; the run row is marked FAILED
                messages.error(request, f"Pipeline failed: {exc}")
            else:
                text = (f"Run #{run.id}: {run.records_loaded} loaded, {run.records_rejected} rejected, "
                        f"{run.records_duplicate} duplicates.")
                (messages.error if run.status == PipelineRun.Status.FAILED else messages.success)(request, text)
        return redirect("ingestion:pipelines")

    runs = Paginator(PipelineRun.objects.order_by("-started_at", "-id"), 25).get_page(request.GET.get("page"))
    return render(request, "ingestion/pipelines.html", {"page_obj": runs, "query": ""})
