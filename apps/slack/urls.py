from django.urls import path

from . import views

app_name = "slack"

urlpatterns = [
    path("commands", views.slash_commands, name="slash_commands"),
    path("interactions", views.interactions, name="interactions"),
    path("events", views.events, name="events"),
]
