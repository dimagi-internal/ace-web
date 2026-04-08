from django.http import JsonResponse
from django.views.decorators.http import require_GET

from .envelope import success_response


@require_GET
def health_check(request):
    return JsonResponse(success_response({"status": "ok"}))
