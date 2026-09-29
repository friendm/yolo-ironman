from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import logout
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from common.signing import storage_url
from common.views import role_required
from documents import services as doc_services
from documents.extraction import low_confidence_fields
from documents.forms import UploadForm, build_confirm_form
from documents.models import Document, DocumentType, ShareLink
from ops import audit

from . import services
from .forms import DeleteAccountForm, JoinCodeForm, VendorBasicsForm

vendor_required = role_required("vendor")


def _vendor(request):
    return getattr(request.user, "vendor", None)


def _needs_basics(view):
    def wrapped(request, *args, **kwargs):
        if _vendor(request) is None:
            return redirect("vendors:basics")
        return view(request, *args, **kwargs)

    wrapped.__name__ = view.__name__
    return wrapped


@vendor_required
@_needs_basics
def home(request):
    vendor = request.user.vendor
    cards = services.document_cards(vendor)
    tone, headline = services.status_summary(cards)
    return render(
        request,
        "vendors/home.html",
        {
            "vendor": vendor,
            "cards": cards,
            "tone": tone,
            "headline": headline,
            "links": services.upcoming_links(vendor),
            "join_form": JoinCodeForm(),
        },
    )


@vendor_required
def basics(request):
    vendor = _vendor(request)
    form = VendorBasicsForm(request.POST or None, request.FILES or None, instance=vendor)
    if request.method == "POST" and form.is_valid():
        vendor = form.save(commit=False)
        vendor.owner_user = request.user
        photo = form.cleaned_data.get("photo")
        if photo:
            if vendor.photo_url:
                default_storage.delete(vendor.photo_url)
            vendor.photo_url = default_storage.save(
                f"vendors/{request.user.id}/photo.{photo.extension}", ContentFile(photo.content)
            )
        created = vendor._state.adding
        vendor.save()
        if created:
            invite = request.session.get("invite_code")
            if invite:
                return redirect("events:join_code", code=invite)
            return redirect("vendors:documents")
        messages.success(request, "Business details saved.")
        return redirect("vendors:home")
    photo = storage_url(vendor.photo_url) if vendor and vendor.photo_url else None
    return render(request, "vendors/basics.html", {"form": form, "vendor": vendor, "photo": photo})


@vendor_required
@_needs_basics
def documents(request):
    vendor = request.user.vendor
    return render(request, "vendors/documents.html", {"cards": services.document_cards(vendor), "vendor": vendor})


@vendor_required
@_needs_basics
def upload(request, key):
    vendor = request.user.vendor
    dtype = get_object_or_404(DocumentType, key=key)
    form = UploadForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        document = doc_services.save_upload(
            vendor, dtype, form.cleaned_data["file"], original_name=request.FILES["file"].name
        )
        audit.record(request.user, "document_upload", document, type=dtype.key)
        return redirect("vendors:confirm", pk=document.pk)
    current = Document.objects.current().filter(vendor=vendor, document_type=dtype).first()
    return render(request, "vendors/upload.html", {"form": form, "dtype": dtype, "current": current})


@vendor_required
@_needs_basics
def confirm(request, pk):
    document = get_object_or_404(Document.objects.visible_to(request.user).select_related("document_type"), pk=pk)
    if document.status != Document.Status.DRAFT:
        return redirect("vendors:documents")
    if document.extraction_status == Document.Extraction.QUEUED:
        # Plain meta refresh every 3 seconds until extraction finishes; no JavaScript needed.
        started = document.created_at
        if timezone.now() - started < timedelta(minutes=2):
            return render(request, "vendors/reading.html", {"document": document})
    low = low_confidence_fields(document.extracted)
    form = build_confirm_form(document, request.POST or None, low=low)
    if request.method == "POST" and form.is_valid():
        doc_services.submit(document, form, request.user)
        messages.success(request, f"{document.document_type.label} submitted. We'll text you once it's verified.")
        return redirect("vendors:documents")
    return render(
        request,
        "vendors/confirm.html",
        {
            "document": document,
            "form": form,
            "low": low,
            "read_ok": document.extraction_status == Document.Extraction.DONE,
        },
    )


@vendor_required
@_needs_basics
def share(request):
    vendor = request.user.vendor
    if request.method == "POST":
        link = ShareLink.objects.create(vendor=vendor, expires_at=timezone.now() + timedelta(days=14))
        audit.record(request.user, "share_link_create", link, entity="share_link")
        messages.success(request, "Share link created. It works for 14 days.")
        return redirect("vendors:share")
    links = vendor.share_links.filter(revoked=False, expires_at__gt=timezone.now()).order_by("-created_at")
    verified = Document.objects.current().filter(vendor=vendor, status=Document.Status.VERIFIED).count()
    return render(request, "vendors/share.html", {"links": links, "verified": verified})


@vendor_required
@_needs_basics
@require_POST
def revoke_share(request, pk):
    link = get_object_or_404(ShareLink, pk=pk, vendor=request.user.vendor)
    link.revoked = True
    link.save(update_fields=["revoked", "updated_at"])
    audit.record(request.user, "share_link_revoke", link, entity="share_link")
    messages.success(request, "Share link turned off.")
    return redirect("vendors:share")


@vendor_required
@_needs_basics
def delete_account(request):
    form = DeleteAccountForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        services.delete_account(request.user.vendor, request.user)
        logout(request)
        messages.success(request, "Your account is closed.")
        return redirect("accounts:landing")
    return render(request, "vendors/delete_account.html", {"form": form})
