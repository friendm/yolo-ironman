import secrets

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.core import signing
from django.core.cache import cache
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from common.phone import format_phone
from common.ratelimit import client_ip, hit
from notifications import services as notify

from .forms import CodeForm, EmailForm, EmailPasswordForm, PhoneForm, RoleForm
from .models import PhoneCode, User

MAGIC_SALT = "magic-link"
MAGIC_MAX_AGE = 15 * 60
BACKEND = "django.contrib.auth.backends.ModelBackend"


def home_url(user):
    """Where a signed-in user lands, based on their role and setup progress."""
    if not user.role:
        return reverse("accounts:choose_role")
    if user.role == User.Role.ADMIN:
        return reverse("ops:queue")
    if user.role == User.Role.VENDOR:
        if not hasattr(user, "vendor"):
            return reverse("vendors:basics")
        return reverse("vendors:home")
    if not hasattr(user, "organization"):
        return reverse("events:org_setup")
    return reverse("events:org_home")


def finish_login(request, user):
    intent = request.session.get("intent")
    invite = request.session.get("invite_code")
    login(request, user, backend=BACKEND)
    if invite:
        request.session["invite_code"] = invite
    if not user.role and intent in (User.Role.VENDOR, User.Role.ORGANIZER):
        user.role = intent
        user.save(update_fields=["role", "updated_at"])
    if user.role == User.Role.VENDOR and invite and hasattr(user, "vendor"):
        return redirect("events:join_code", code=invite)
    return redirect(home_url(user))


def landing(request):
    if request.user.is_authenticated:
        return redirect(home_url(request.user))
    return render(request, "landing.html")


def _start(request, intent, template):
    if request.user.is_authenticated:
        return redirect(home_url(request.user))
    request.session["intent"] = intent
    if request.GET.get("invite"):
        request.session["invite_code"] = request.GET["invite"].strip().upper()[:12]
    form = PhoneForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        phone = form.cleaned_data["phone"]
        ip_ok = hit("otp-ip", client_ip(request), limit=10, window_seconds=600)
        phone_ok = hit("otp-phone", phone, limit=3, window_seconds=600)
        if not (ip_ok and phone_ok):
            form.add_error(None, "Too many codes requested. Wait a few minutes and try again.")
        else:
            _, code = PhoneCode.issue(phone)
            user = User.objects.filter(phone=phone).first()
            notify.send_sms(user, "otp", {"code": code}, phone=phone, transactional=True)
            request.session["otp_phone"] = phone
            return redirect("accounts:code")
    return render(request, template, {"form": form, "intent": intent})


def vendor_start(request):
    return _start(request, User.Role.VENDOR, "accounts/vendor_start.html")


def login_view(request):
    return _start(request, request.session.get("intent", ""), "accounts/login.html")


def org_start(request):
    if request.user.is_authenticated:
        return redirect(home_url(request.user))
    request.session["intent"] = User.Role.ORGANIZER
    return render(request, "accounts/org_start.html", {"phone_form": PhoneForm(), "email_form": EmailForm()})


def enter_code(request):
    phone = request.session.get("otp_phone")
    if not phone:
        return redirect("accounts:login")
    form = CodeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        if PhoneCode.verify(phone, form.cleaned_data["code"]):
            user, _ = User.objects.get_or_create(phone=phone)
            if not user.is_active:
                form.add_error(None, "This account is closed.")
            else:
                del request.session["otp_phone"]
                return finish_login(request, user)
        else:
            form.add_error("code", "That code didn't work. Check the text message or request a new code.")
    return render(request, "accounts/code.html", {"form": form, "phone": format_phone(phone)})


@require_POST
def email_link(request):
    form = EmailForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Enter a valid email address.")
        return redirect("accounts:org_start")
    email = form.cleaned_data["email"].lower()
    if hit("magic", email, limit=3, window_seconds=600) and hit("magic-ip", client_ip(request), 10, 600):
        token = signing.dumps({"email": email, "n": secrets.token_hex(8)}, salt=MAGIC_SALT)
        link = settings.SITE_URL + reverse("accounts:magic", args=[token])
        user = User.objects.filter(email__iexact=email).first()
        notify.send_email(user, "magic_link", {"link": link}, email=email)
    return render(request, "accounts/check_email.html", {"email": email})


def magic(request, token):
    try:
        data = signing.loads(token, salt=MAGIC_SALT, max_age=MAGIC_MAX_AGE)
    except signing.BadSignature:
        messages.error(request, "That sign-in link has expired. Request a new one.")
        return redirect("accounts:org_start")
    if not cache.add(f"magic-used:{data['n']}", 1, timeout=MAGIC_MAX_AGE + 60):
        messages.error(request, "That sign-in link was already used. Request a new one.")
        return redirect("accounts:org_start")
    user = User.objects.filter(email__iexact=data["email"]).first()
    if user is None:
        user = User.objects.create_user(email=data["email"], role=User.Role.ORGANIZER)
    if not user.is_active:
        messages.error(request, "This account is closed.")
        return redirect("accounts:org_start")
    request.session["intent"] = User.Role.ORGANIZER
    return finish_login(request, user)


def email_login(request):
    form = EmailPasswordForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        if not hit("pw-ip", client_ip(request), limit=10, window_seconds=600):
            form.add_error(None, "Too many attempts. Wait a few minutes and try again.")
        else:
            user = User.objects.filter(email__iexact=form.cleaned_data["email"], is_active=True).first()
            if user and user.check_password(form.cleaned_data["password"]):
                return finish_login(request, user)
            form.add_error(None, "Email or password is incorrect.")
    return render(request, "accounts/email_login.html", {"form": form})


def choose_role(request):
    if not request.user.is_authenticated:
        return redirect("accounts:login")
    if request.user.role:
        return redirect(home_url(request.user))
    form = RoleForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        request.user.role = form.cleaned_data["role"]
        request.user.save(update_fields=["role", "updated_at"])
        return redirect(home_url(request.user))
    return render(request, "accounts/choose_role.html", {"form": form})


@require_POST
def logout_view(request):
    logout(request)
    return redirect("accounts:landing")


def terms(request):
    return render(request, "legal/terms.html")


def privacy(request):
    return render(request, "legal/privacy.html")
