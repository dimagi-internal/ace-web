"""Migration stub for the retired cloud mobile emulator.

The cloud Android emulator ace-web used to orchestrate was retired on
2026-10-14 — Android emulators are now canopy-web capability leases that the
agent claims itself (ACE's ``lease`` mobile backend). This app exists ONLY to
carry ``migrations/0002_delete_mobilelaunchscriptpatch.py``, which drops the
``mobile_launch_script_patch`` table. Delete the whole app (and its
INSTALLED_APPS entry) once 0002 has run in prod.
"""

from django.apps import AppConfig


class MobileConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.mobile"
    label = "mobile"
