from rest_framework import mixins, status, viewsets
from rest_framework.response import Response

from apps.logs.models import PipelineRun

from .serializers import PipelineRunSerializer, PipelineUploadSerializer
from .services import run_pipeline_for_upload


class PipelineRunViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """GET /api/pipelines/, GET /api/pipelines/<id>/, POST /api/pipelines/ (multipart `file` upload)."""

    serializer_class = PipelineRunSerializer
    queryset = PipelineRun.objects.order_by("-started_at", "-id")

    def create(self, request, *args, **kwargs):
        upload = PipelineUploadSerializer(data=request.data)
        upload.is_valid(raise_exception=True)
        data = upload.validated_data
        run = run_pipeline_for_upload(
            data["file"], service=data.get("service") or None, host=data.get("host") or None
        )
        code = status.HTTP_422_UNPROCESSABLE_ENTITY if run.status == PipelineRun.Status.FAILED \
            else status.HTTP_201_CREATED
        return Response(PipelineRunSerializer(run).data, status=code)
