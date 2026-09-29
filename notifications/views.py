from django.conf import settings
from django.http import HttpResponse, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from accounts.models import User
from common.phone import InvalidPhone, normalize_phone

STOP_WORDS = {"stop", "stopall", "unsubscribe", "cancel", "end", "quit"}
START_WORDS = {"start", "yes", "unstop"}


@csrf_exempt
@require_POST
def twilio_inbound(request):
    """Twilio inbound SMS webhook: record STOP / START opt-outs."""
    if settings.TWILIO_AUTH_TOKEN:
        from twilio.request_validator import RequestValidator

        validator = RequestValidator(settings.TWILIO_AUTH_TOKEN)
        url = settings.SITE_URL + request.path
        if not validator.validate(url, request.POST.dict(), request.headers.get("X-Twilio-Signature", "")):
            return HttpResponseForbidden()
    elif not settings.DEBUG:
        return HttpResponseForbidden()
    word = request.POST.get("Body", "").strip().lower()
    try:
        phone = normalize_phone(request.POST.get("From", ""))
    except InvalidPhone:
        phone = None
    if phone and (word in STOP_WORDS or word in START_WORDS):
        User.objects.filter(phone=phone).update(sms_opt_out=word in STOP_WORDS)
    return HttpResponse('<?xml version="1.0" encoding="UTF-8"?><Response></Response>', content_type="text/xml")
