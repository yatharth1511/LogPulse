from django.urls import path

from . import views

app_name = "logs"
urlpatterns = [
    path("", views.explorer, name="explorer"),
    path("<int:pk>/", views.detail, name="detail"),
]
