from django.urls import path

from . import views

app_name = "ingestion"
urlpatterns = [path("", views.pipelines, name="pipelines")]
