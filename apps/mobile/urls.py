from django.urls import path

from . import views

urlpatterns = [
    path("status", views.status, name="mobile_status"),
    path("ensure-running", views.ensure_running, name="mobile_ensure_running"),
    path("install-apk", views.install_apk, name="mobile_install_apk"),
    path("run-recipe", views.run_recipe, name="mobile_run_recipe"),
    path("save-snapshot", views.save_snapshot, name="mobile_save_snapshot"),
    path("load-snapshot", views.load_snapshot, name="mobile_load_snapshot"),
    path("capture-ui-dump", views.capture_ui_dump, name="mobile_capture_ui_dump"),
    path("stop", views.stop, name="mobile_stop"),
]
