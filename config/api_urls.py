from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.analytics.api import AnalyticsView
from apps.ingestion.api import PipelineRunViewSet
from apps.logs.api import LogEventViewSet, ServiceViewSet

router = DefaultRouter()
router.register("logs", LogEventViewSet, basename="log")
router.register("services", ServiceViewSet, basename="service")
router.register("pipelines", PipelineRunViewSet, basename="pipeline")

urlpatterns = [
    path("analytics/", AnalyticsView.as_view(), name="analytics"),
    path("", include(router.urls)),
]
