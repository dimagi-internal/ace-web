from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    # apps.common.urls is created in Task 3. `manage.py check` will fail
    # between this commit and Task 3's commit; that's expected.
    path("api/", include("apps.common.urls")),
]
