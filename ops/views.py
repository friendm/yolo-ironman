from datetime import timedelta

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import F, Min, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from common.signing import storage_url
from common.views import role_required
from documents import services as doc_services
from documents.extraction import low_confidence_fields
from documents.forms import build_confirm_form, confirm_form_class
from documents.models import Document, DocumentType
from events.models import Event, Organization, RequirementTemplate
from notifications import services as notify
from vendors.models import Vendor

from . import audit, metrics
from .forms import AuditFilterForm, DirectorySearchForm, DocumentTypeForm, RequirementTemplateForm, VerifyForm
from .models import AuditLog

admin_required = role_required("admin")


@admin_required
def queue(request):
    today = timezone.localdate()
    pending = (
        Document.objects.filter(status=Document.Status.PENDING, superseded_by__isnull=True)
        .select_related("vendor", "document_type", "event")
        .annotate(
            soonest_event=Min(
                "vendor__event_links__event__start_date",
                filter=Q(vendor__event_links__status="joined", vendor__event_links__event__start_date__gte=today),
            )
        )
        .order_by(F("soonest_event").asc(nulls_last=True), "submitted_at")
    )
    return render(request, "ops/queue.html", {"documents": pending})


def _field_rows(document, form_class):
    extracted = document.extracted or {}
    confirmed = document.confirmed or {}
    low = low_confidence_fields(extracted)
    rows = []
    for name, field in form_class.base_fields.items():
        a, b = extracted.get(name), confirmed.get(name)
        rows.append(
            {
                "label": field.label or name,
                "extracted": a,
                "confirmed": b,
                "low": name in low,
                "differs": bool(confirmed)
                and a not in (None, "")
                and str(a).strip().lower() != str(b or "").strip().lower(),
            }
        )
    return rows


@admin_required
def review(request, pk):
    document = get_object_or_404(Document.objects.select_related("vendor__owner_user", "document_type", "event"), pk=pk)
    form_class = confirm_form_class(document.document_type)
    fields_form = build_confirm_form(
        document,
        request.POST or None,
        initial_source=document.confirmed or document.extracted or {},
        prefix="f",
        low=low_confidence_fields(document.extracted),
    )
    verify_form = VerifyForm(request.POST or None)
    if request.method == "POST":
        if verify_form.is_valid():
            decision = verify_form.cleaned_data["decision"]
            notes = verify_form.cleaned_data["notes"]
            if decision == "verify" and fields_form.is_valid():
                doc_services.verify(document, request.user, verify_form.cleaned_data["method"], notes, fields_form)
                messages.success(request, f"Verified {document.document_type.label} for {document.vendor}.")
                return redirect("ops:queue")
            if decision == "reject":
                doc_services.reject(
                    document,
                    request.user,
                    verify_form.cleaned_data["reason"],
                    notes,
                    verify_form.cleaned_data["method"],
                )
                messages.success(request, f"Rejected. We texted {document.vendor} the reason.")
                return redirect("ops:queue")
    audit.record(request.user, "document_view", document, vendor=document.vendor_id, via="ops_review")
    history = Document.objects.filter(vendor=document.vendor, document_type=document.document_type).exclude(
        pk=document.pk
    )
    return render(
        request,
        "ops/review.html",
        {
            "document": document,
            "file_url": storage_url(document.file_path),
            "rows": _field_rows(document, form_class),
            "fields_form": fields_form,
            "verify_form": verify_form,
            "flags": doc_services.admin_flags(document),
            "history": history[:10],
            "low": low_confidence_fields(document.extracted),
        },
    )


@admin_required
@require_POST
def agent_verify(request, pk):
    """Draft and send an email asking the agent to confirm the policy is active."""
    document = get_object_or_404(Document.objects.select_related("vendor"), pk=pk)
    vendor = document.vendor
    if not vendor.agent_email:
        messages.error(request, "This vendor has no agent email on file.")
        return redirect("ops:review", pk=pk)
    fields = document.confirmed or document.extracted or {}
    lines = [
        f"Insured: {vendor.business_name}",
        f"Insurer: {fields.get('insurer_name') or 'not listed'}",
        f"Policy number: {fields.get('policy_number') or 'not listed'}",
        f"Policy period: {fields.get('effective_date') or '?'} to {fields.get('expiration_date') or '?'}",
    ]
    for key, label in (
        ("gl_per_occurrence", "GL each occurrence"),
        ("gl_aggregate", "GL aggregate"),
        ("auto_liability", "Auto liability"),
    ):
        if fields.get(key):
            lines.append(f"{label}: ${int(fields[key]):,}")
    notify.send_email(
        None,
        "agent_verify",
        {"agent": vendor.agent_name or "there", "vendor": vendor.business_name, "summary": "\n".join(lines)},
        email=vendor.agent_email,
    )
    audit.record(request.user, "agent_verify_email", document, to=vendor.agent_email)
    messages.success(request, f"Email sent to {vendor.agent_email}. Log their reply in the reviewer notes.")
    return redirect("ops:review", pk=pk)


@admin_required
def expirations(request):
    today = timezone.localdate()
    base = Document.objects.current().select_related("vendor", "document_type").filter(expiration_date__isnull=False)
    expiring = base.filter(expiration_date__gte=today, expiration_date__lte=today + timedelta(days=30)).order_by(
        "expiration_date"
    )
    expired = base.filter(Q(expiration_date__lt=today) | Q(status=Document.Status.EXPIRED)).order_by(
        "-expiration_date"
    )[:100]
    return render(request, "ops/expirations.html", {"expiring": expiring, "expired": expired, "today": today})


@admin_required
@require_POST
def send_expiration_reminder(request, pk):
    from django.urls import reverse

    document = get_object_or_404(Document.objects.select_related("vendor__owner_user", "document_type"), pk=pk)
    notify.send_sms(
        document.vendor.owner_user,
        "document_expiring",
        {
            "document": document.document_type.label,
            "date": f"{document.expiration_date:%b %-d}",
            "link": notify.absolute(reverse("vendors:upload", args=[document.document_type.key])),
        },
    )
    audit.record(request.user, "expiration_reminder_manual", document)
    messages.success(request, f"Reminder sent to {document.vendor}.")
    return redirect("ops:expirations")


@admin_required
def directory(request):
    form = DirectorySearchForm(request.GET or None)
    q = form.cleaned_data["q"] if form.is_valid() else ""
    vendors = Vendor.objects.select_related("owner_user")
    orgs = Organization.objects.select_related("owner_user")
    events = Event.objects.select_related("organization")
    if q:
        vendors = vendors.filter(Q(business_name__icontains=q) | Q(owner_user__phone__icontains=q))
        orgs = orgs.filter(Q(name__icontains=q) | Q(owner_user__email__icontains=q))
        events = events.filter(Q(name__icontains=q) | Q(invite_code__iexact=q))
    return render(
        request,
        "ops/directory.html",
        {"form": form, "vendors": vendors[:50], "orgs": orgs[:50], "events": events.order_by("-start_date")[:50]},
    )


@admin_required
def vendor_detail(request, pk):
    vendor = get_object_or_404(Vendor.objects.select_related("owner_user"), pk=pk)
    documents = vendor.documents.select_related("document_type").order_by("document_type__sort_order", "-created_at")
    links = vendor.event_links.select_related("event__organization")
    return render(request, "ops/vendor_detail.html", {"vendor": vendor, "documents": documents, "links": links})


@admin_required
def document_types(request, pk=None):
    instance = get_object_or_404(DocumentType, pk=pk) if pk else None
    form = DocumentTypeForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        saved = form.save()
        audit.record(request.user, "document_type_save", saved)
        messages.success(request, f"Saved {saved.label}.")
        return redirect("ops:document_types")
    return render(
        request, "ops/document_types.html", {"form": form, "types": DocumentType.objects.all(), "instance": instance}
    )


@admin_required
def templates(request, pk=None):
    instance = get_object_or_404(RequirementTemplate, pk=pk) if pk else None
    form = RequirementTemplateForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        saved = form.save()
        if saved.is_default:
            RequirementTemplate.objects.exclude(pk=saved.pk).update(is_default=False)
        audit.record(request.user, "requirement_template_save", saved)
        messages.success(request, f"Saved {saved.name}.")
        return redirect("ops:templates")
    return render(
        request,
        "ops/templates.html",
        {
            "form": form,
            "templates": RequirementTemplate.objects.prefetch_related("required_document_types"),
            "instance": instance,
        },
    )


@admin_required
def audit_view(request):
    form = AuditFilterForm(request.GET or None)
    logs = AuditLog.objects.select_related("actor_user")
    if form.is_valid():
        entity_id = form.cleaned_data.get("entity_id")
        if entity_id:
            doc_ids = list(Document.objects.filter(vendor_id=entity_id).values_list("id", flat=True))
            logs = logs.filter(Q(entity_id=entity_id) | Q(entity_id__in=doc_ids) | Q(details__vendor=str(entity_id)))
        if form.cleaned_data.get("action"):
            logs = logs.filter(action=form.cleaned_data["action"])
    page = Paginator(logs, 50).get_page(request.GET.get("page"))
    query = request.GET.copy()
    query.pop("page", None)
    return render(request, "ops/audit.html", {"form": form, "page": page, "query": query.urlencode()})


@admin_required
def metrics_view(request):
    return render(request, "ops/metrics.html", {"m": metrics.summary()})
