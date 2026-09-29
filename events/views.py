from datetime import timedelta

from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from common.ratelimit import client_ip, hit
from common.views import role_required
from documents import services as doc_services
from documents.forms import UploadForm
from documents.models import Document, DocumentType
from notifications import services as notify
from ops import audit
from vendors.forms import JoinCodeForm
from vendors.models import Vendor

from . import exports, services
from .forms import EventForm, OrganizationForm, RequirementForm, VendorSearchForm
from .models import AICertificateRequest, Event, EventVendor
from .status import current_documents, evaluate

organizer_required = role_required("organizer")
vendor_required = role_required("vendor")
BULK_REMINDER_COOLDOWN = timedelta(hours=24)


# ---------------------------------------------------------------- organizer


def _org(request):
    return getattr(request.user, "organization", None)


def _needs_org(view):
    def wrapped(request, *args, **kwargs):
        if _org(request) is None:
            return redirect("events:org_setup")
        return view(request, *args, **kwargs)

    wrapped.__name__ = view.__name__
    return wrapped


def _org_event(request, pk):
    return get_object_or_404(Event.objects.visible_to(request.user).select_related("organization"), pk=pk)


@organizer_required
def org_setup(request):
    org = _org(request)
    user = request.user
    initial = {"email": user.email, "full_name": user.full_name}
    form = OrganizationForm(request.POST or None, instance=org, initial=initial)
    if request.method == "POST" and form.is_valid():
        from accounts.models import User

        email = form.cleaned_data.get("email")
        if email and User.objects.filter(email__iexact=email).exclude(pk=user.pk).exists():
            form.add_error("email", "Another account already uses this email.")
        else:
            with transaction.atomic():
                org = form.save(commit=False)
                org.owner_user = user
                org.save()
                user.email = email or user.email
                user.full_name = form.cleaned_data.get("full_name") or user.full_name
                if form.cleaned_data.get("password"):
                    user.set_password(form.cleaned_data["password"])
                user.save()
            messages.success(request, "Organization saved.")
            return redirect("events:org_home")
    return render(request, "events/org_setup.html", {"form": form, "org": org})


@organizer_required
@_needs_org
def org_home(request):
    events = (
        Event.objects.visible_to(request.user)
        .annotate(
            green=Count("vendor_links", filter=Q(vendor_links__status="joined", vendor_links__computed_status="green")),
            yellow=Count(
                "vendor_links", filter=Q(vendor_links__status="joined", vendor_links__computed_status="yellow")
            ),
            red=Count("vendor_links", filter=Q(vendor_links__status="joined", vendor_links__computed_status="red")),
            invited=Count("vendor_links", filter=Q(vendor_links__status="invited")),
        )
        .order_by("-is_standing", "start_date")
    )
    today = timezone.localdate()
    upcoming = [e for e in events if e.is_standing or not e.end_date or e.end_date >= today]
    past = [e for e in events if not e.is_standing and e.end_date and e.end_date < today]
    return render(
        request, "events/org_home.html", {"upcoming": upcoming, "past": past, "org": request.user.organization}
    )


def _save_event(request, event, standing):
    initial = services.default_requirement_values() if event is None else None
    requirement = getattr(event, "requirement", None) if event else None
    event_form = EventForm(request.POST or None, instance=event, standing=standing, prefix="event")
    req_form = RequirementForm(request.POST or None, instance=requirement, initial=initial, prefix="req")
    if request.method == "POST" and event_form.is_valid() and req_form.is_valid():
        with transaction.atomic():
            saved = event_form.save(commit=False)
            if event is None:
                saved.organization = request.user.organization
                saved.is_standing = standing
            saved.save()
            req = req_form.save(commit=False)
            req.event = saved
            req.save()
            req_form.save_m2m()
        saved.refresh_from_db()
        services.recompute_for_event(saved)
        audit.record(request.user, "event_save", saved)
        return saved, event_form, req_form
    return None, event_form, req_form


@organizer_required
@_needs_org
def event_new(request):
    standing = request.GET.get("standing") == "1" or request.POST.get("standing") == "1"
    if standing and not request.user.organization.recurring_host:
        standing = False
    saved, event_form, req_form = _save_event(request, None, standing)
    if saved:
        messages.success(request, "Event created. Invite vendors with the link or code below.")
        return redirect("events:org_invite", pk=saved.pk)
    return render(
        request,
        "events/event_form.html",
        {"event_form": event_form, "req_form": req_form, "standing": standing, "event": None},
    )


@organizer_required
@_needs_org
def event_edit(request, pk):
    event = _org_event(request, pk)
    services.ensure_requirement(event)
    saved, event_form, req_form = _save_event(request, event, event.is_standing)
    if saved:
        messages.success(request, "Event updated. Vendor statuses were recalculated.")
        return redirect("events:org_event", pk=saved.pk)
    return render(
        request,
        "events/event_form.html",
        {"event_form": event_form, "req_form": req_form, "standing": event.is_standing, "event": event},
    )


STATUS_FILTERS = {"green", "yellow", "red", "invited"}


@organizer_required
@_needs_org
def org_event(request, pk):
    event = _org_event(request, pk)
    services.ensure_requirement(event)
    links = event.vendor_links.exclude(status="removed").select_related("vendor").order_by("vendor__business_name")
    joined = [link for link in links if link.status == "joined"]
    counts = {
        "green": sum(1 for link in joined if link.computed_status == "green"),
        "yellow": sum(1 for link in joined if link.computed_status == "yellow"),
        "red": sum(1 for link in joined if link.computed_status == "red"),
        "invited": sum(1 for link in links if link.status == "invited"),
    }
    active = request.GET.get("status", "")
    if active in STATUS_FILTERS:
        if active == "invited":
            links = [link for link in links if link.status == "invited"]
        else:
            links = [link for link in joined if link.computed_status == active]
    can_remind = (
        not event.last_bulk_reminder_at or timezone.now() - event.last_bulk_reminder_at >= BULK_REMINDER_COOLDOWN
    )
    return render(
        request,
        "events/org_event.html",
        {"event": event, "links": links, "counts": counts, "active": active, "can_remind": can_remind},
    )


@organizer_required
@_needs_org
def org_invite(request, pk):
    event = _org_event(request, pk)
    form = VendorSearchForm(request.GET or None)
    results = []
    if form.is_valid() and form.cleaned_data["q"]:
        if hit("vendor-search", request.user.pk, limit=60, window_seconds=600):
            linked = event.vendor_links.exclude(status="removed").values("vendor_id")
            results = (
                Vendor.objects.filter(business_name__icontains=form.cleaned_data["q"], deleted_at__isnull=True)
                .exclude(pk__in=linked)
                .order_by("business_name")[:20]
            )
    invited = event.vendor_links.filter(status="invited").select_related("vendor")
    return render(
        request, "events/org_invite.html", {"event": event, "form": form, "results": results, "invited": invited}
    )


@organizer_required
@_needs_org
@require_POST
def org_invite_vendor(request, pk):
    event = _org_event(request, pk)
    vendor = get_object_or_404(Vendor, pk=request.POST.get("vendor_id"), deleted_at__isnull=True)
    _, created = services.invite_vendor(event, vendor, request.user)
    if created:
        messages.success(request, f"Invited {vendor.business_name}. We texted them the link.")
    return redirect("events:org_invite", pk=event.pk)


@organizer_required
@_needs_org
def org_vendor(request, pk, vendor_id):
    """Vendor detail: only reachable through a joined event_vendors row for this organizer's event."""
    event = _org_event(request, pk)
    link = get_object_or_404(EventVendor, event=event, vendor_id=vendor_id, status="joined")
    vendor = link.vendor
    required = list(event.requirement.required_document_types.all())
    docs = current_documents(vendor)
    rows = [{"type": dtype, "doc": docs.get(dtype.id)} for dtype in required]
    audit.record(request.user, "vendor_detail_view", vendor, event=event.id)
    return render(request, "events/org_vendor.html", {"event": event, "link": link, "vendor": vendor, "rows": rows})


@organizer_required
@_needs_org
@require_POST
def org_remind(request, pk):
    """One SMS per red or yellow vendor listing what is missing. Once per event per 24 hours."""
    with transaction.atomic():
        event = get_object_or_404(Event.objects.visible_to(request.user).select_for_update(), pk=pk)
        now = timezone.now()
        if event.last_bulk_reminder_at and now - event.last_bulk_reminder_at < BULK_REMINDER_COOLDOWN:
            messages.error(request, "You already sent a reminder in the last 24 hours.")
            return redirect("events:org_event", pk=pk)
        event.last_bulk_reminder_at = now
        event.save(update_fields=["last_bulk_reminder_at", "updated_at"])
    links = event.vendor_links.filter(status="joined", computed_status__in=["red", "yellow"]).select_related(
        "vendor__owner_user"
    )
    sent = 0
    for link in links:
        notify.send_sms(
            link.vendor.owner_user,
            "bulk_reminder",
            {
                "org": event.organization.name,
                "event": event.name,
                "missing": "; ".join(link.status_reasons) or "updated documents",
                "link": notify.absolute(reverse("events:vendor_event", args=[event.pk])),
            },
            dedupe_key=f"bulk:{event.pk}:{now:%Y%m%d%H%M}:{link.vendor_id}",
        )
        sent += 1
    audit.record(request.user, "bulk_reminder", event, recipients=sent)
    messages.success(request, f"Reminder sent to {sent} vendor{'s' if sent != 1 else ''}.")
    return redirect("events:org_event", pk=pk)


@organizer_required
@_needs_org
def export_csv(request, pk):
    event = _org_event(request, pk)
    response = HttpResponse(exports.vendors_csv(event), content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{slugify(event.name)}-vendors.csv"'
    audit.record(request.user, "export_csv", event)
    return response


@organizer_required
@_needs_org
def export_zip(request, pk):
    event = _org_event(request, pk)
    services.ensure_requirement(event)
    response = HttpResponse(exports.verified_zip(event, request.user), content_type="application/zip")
    response["Content-Disposition"] = f'attachment; filename="{slugify(event.name)}-documents.zip"'
    audit.record(request.user, "export_zip", event)
    return response


# ---------------------------------------------------------------- vendor


def invite(request, code):
    """Invite link. New vendors sign up first; the code is kept and they auto-join after onboarding."""
    event = Event.objects.filter(invite_code=code.upper()).select_related("organization").first()
    if event is None:
        raise Http404
    request.session["invite_code"] = event.invite_code
    if request.user.is_authenticated and request.user.role == "vendor":
        return redirect("events:join_code", code=event.invite_code)
    return render(request, "events/invite_landing.html", {"event": event})


@vendor_required
def join(request):
    form = JoinCodeForm(request.POST or request.GET or None)
    if form.is_valid():
        return redirect("events:join_code", code=form.cleaned_data["code"])
    return render(request, "events/join.html", {"form": form})


@vendor_required
def join_code(request, code):
    vendor = getattr(request.user, "vendor", None)
    if vendor is None:
        request.session["invite_code"] = code.upper()
        return redirect("vendors:basics")
    if not hit("invite-lookup", request.user.pk, limit=20, window_seconds=600):
        return HttpResponse("Too many invite codes tried. Wait a few minutes.", status=429)
    event = Event.objects.filter(invite_code=code.upper()).exclude(status=Event.Status.CLOSED).first()
    if event is None:
        messages.error(request, "We couldn't find an open event with that code.")
        return redirect("events:join")
    services.ensure_requirement(event)
    request.session.pop("invite_code", None)
    link = EventVendor.objects.filter(event=event, vendor=vendor, status="joined").first()
    if link:
        return redirect("events:vendor_event", pk=event.pk)
    if request.method == "POST":
        services.join_event(vendor, event, request.user)
        messages.success(request, f"You joined {event.name}. {event.organization.name} can now see your documents.")
        return redirect("events:vendor_event", pk=event.pk)
    preview = evaluate(event, vendor)
    return render(request, "events/join_confirm.html", {"event": event, "preview": preview})


@vendor_required
def vendor_event(request, pk):
    vendor = getattr(request.user, "vendor", None)
    link = get_object_or_404(
        EventVendor.objects.visible_to(request.user).select_related("event__organization", "event__requirement"),
        event_id=pk,
        vendor=vendor,
    )
    if link.status == "removed":
        raise Http404
    event = link.event
    last_request = AICertificateRequest.objects.filter(event=event, vendor=vendor).order_by("-sent_at").first()
    return render(
        request,
        "events/vendor_event.html",
        {"event": event, "link": link, "vendor": vendor, "last_request": last_request},
    )


@vendor_required
@require_POST
def ai_request(request, pk):
    """Email the vendor's agent the event's exact additional insured wording and a secure upload link."""
    vendor = request.user.vendor
    link = get_object_or_404(EventVendor, event_id=pk, vendor=vendor, status="joined")
    event = link.event
    wording = event.requirement.additional_insured_text.strip()
    if not vendor.agent_email:
        messages.error(request, "Add your insurance agent's email in Business details first.")
        return redirect("vendors:basics")
    if not wording:
        messages.error(request, "This event hasn't listed additional insured wording yet.")
        return redirect("events:vendor_event", pk=pk)
    recent = AICertificateRequest.objects.filter(
        event=event, vendor=vendor, sent_at__gt=timezone.now() - timedelta(hours=1)
    ).exists()
    if recent:
        messages.error(request, "A request was sent in the last hour. Give your agent a little time.")
        return redirect("events:vendor_event", pk=pk)
    req = AICertificateRequest.objects.create(
        event=event,
        vendor=vendor,
        sent_to_email=vendor.agent_email,
        wording=wording,
        token_expires_at=timezone.now() + timedelta(days=30),
    )
    dates = f"{event.start_date:%b %-d, %Y}" if event.start_date else "ongoing"
    if event.end_date and event.end_date != event.start_date:
        dates += f" to {event.end_date:%b %-d, %Y}"
    notify.send_email(
        None,
        "ai_request",
        {
            "agent": vendor.agent_name or "there",
            "vendor": vendor.business_name,
            "event": event.name,
            "dates": dates,
            "wording": wording,
            "link": req.upload_url(),
        },
        email=vendor.agent_email,
    )
    audit.record(request.user, "ai_request_sent", req, entity="ai_certificate_request", event=event.id)
    messages.success(request, f"We emailed {vendor.agent_email} with the exact wording and an upload link.")
    return redirect("events:vendor_event", pk=pk)


def agent_upload(request, token):
    """Agents upload a certificate without an account; it enters the admin queue linked to the event."""
    if not hit("agent-upload", client_ip(request), limit=30, window_seconds=600):
        return HttpResponse("Too many requests. Try again in a few minutes.", status=429)
    req = AICertificateRequest.objects.select_related("event", "vendor").filter(upload_token=token).first()
    if req is None or req.token_expires_at < timezone.now():
        return render(request, "events/agent_upload_expired.html", status=410)
    form = UploadForm(request.POST or None, request.FILES or None)
    done = False
    if request.method == "POST" and form.is_valid():
        coi = DocumentType.objects.get(key="coi")
        document = doc_services.save_upload(
            req.vendor,
            coi,
            form.cleaned_data["file"],
            original_name=request.FILES["file"].name,
            source=Document.Source.AGENT,
            event=req.event,
        )
        req.status = AICertificateRequest.Status.RECEIVED
        req.save(update_fields=["status", "updated_at"])
        audit.record(None, "agent_upload", document, event=req.event_id, request=req.id)
        done = True
    return render(request, "events/agent_upload.html", {"req": req, "form": form, "done": done})
