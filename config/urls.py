from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("config.api_urls")),
    path("", include("apps.analytics.urls")),
    path("logs/", include("apps.logs.urls")),
    path("pipelines/", include("apps.ingestion.urls")),
]
