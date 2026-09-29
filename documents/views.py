import mimetypes

from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.files.storage import default_storage
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET

from common.ratelimit import client_ip, hit
from common.signing import storage_url, unsign_local_path
from ops import audit

from .models import Document, ShareLink


@login_required
@require_GET
def view_document(request, pk):
    """Every document view or download is written to the audit log, then redirected to a 10-minute URL."""
    document = get_object_or_404(Document.objects.visible_to(request.user), pk=pk)
    action = "document_download" if request.GET.get("download") else "document_view"
    audit.record(request.user, action, document, vendor=document.vendor_id, via="app")
    return redirect(storage_url(document.file_path))


@login_required
@require_GET
def thumbnail(request, pk):
    document = get_object_or_404(Document.objects.visible_to(request.user), pk=pk)
    if not document.thumbnail_path:
        raise Http404
    audit.record(request.user, "document_thumbnail_view", document, vendor=document.vendor_id)
    return redirect(storage_url(document.thumbnail_path))


@require_GET
def signed_file(request, token):
    """Serve a private local file behind a signed, expiring token (used when S3 is not configured)."""
    try:
        path = unsign_local_path(token)
    except signing.BadSignature:
        return HttpResponse("This link has expired. Go back and open the document again.", status=410)
    if not default_storage.exists(path):
        raise Http404
    content_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
    response = FileResponse(default_storage.open(path, "rb"), content_type=content_type)
    response["Cache-Control"] = "private, no-store"
    # Allow the admin review page to show the file in a same-origin frame.
    response["X-Frame-Options"] = "SAMEORIGIN"
    response["Content-Security-Policy"] = "default-src 'none'; img-src 'self'; frame-ancestors 'self'"
    return response


def _live_share(token):
    link = ShareLink.objects.select_related("vendor").filter(token=token, revoked=False).first()
    if link is None or link.expires_at < timezone.now():
        return None
    return link


def _share_rate_ok(request):
    return hit("share", client_ip(request), limit=60, window_seconds=600)


@require_GET
def share(request, token):
    if not _share_rate_ok(request):
        return HttpResponse("Too many requests. Try again in a few minutes.", status=429)
    link = _live_share(token)
    if link is None:
        return render(request, "documents/share_expired.html", status=410)
    documents = (
        Document.objects.current()
        .filter(vendor=link.vendor, status=Document.Status.VERIFIED)
        .select_related("document_type", "coi")
        .order_by("document_type__sort_order")
    )
    audit.record(request.user, "share_view", link, entity="share_link", vendor=link.vendor_id, ip=client_ip(request))
    return render(request, "documents/share.html", {"link": link, "vendor": link.vendor, "documents": documents})


@require_GET
def share_document(request, token, pk):
    if not _share_rate_ok(request):
        return HttpResponse("Too many requests. Try again in a few minutes.", status=429)
    link = _live_share(token)
    if link is None:
        return render(request, "documents/share_expired.html", status=410)
    document = get_object_or_404(
        Document.objects.current().filter(vendor=link.vendor, status=Document.Status.VERIFIED), pk=pk
    )
    audit.record(
        request.user,
        "document_view",
        document,
        vendor=document.vendor_id,
        via="share_link",
        share_link=link.id,
        ip=client_ip(request),
    )
    return redirect(storage_url(document.file_path))
