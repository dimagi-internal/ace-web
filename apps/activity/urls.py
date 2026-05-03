from django.urls import path

from . import views

urlpatterns = [
    path("", views.activity_feed, name="activity_feed"),
]
