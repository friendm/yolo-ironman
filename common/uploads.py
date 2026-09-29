"""Upload validation and image normalisation (HEIC to JPG, thumbnails)."""

import io
from dataclasses import dataclass

from django.conf import settings
from django.core.exceptions import ValidationError
from PIL import Image, ImageOps

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
except ImportError:  # pragma: no cover
    pillow_heif = None

ALLOWED_EXTENSIONS = {"pdf", "jpg", "jpeg", "png", "heic", "heif"}


@dataclass
class CleanUpload:
    content: bytes
    extension: str
    content_type: str
    thumbnail: bytes | None


def sniff(head):
    if head.startswith(b"%PDF"):
        return "pdf"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head[4:8] == b"ftyp" and head[8:12] in {b"heic", b"heix", b"mif1", b"msf1", b"heim", b"heis", b"hevc"}:
        return "heic"
    return None


def make_thumbnail(image, size=(480, 480)):
    thumb = image.copy()
    thumb.thumbnail(size)
    if thumb.mode not in ("RGB", "L"):
        thumb = thumb.convert("RGB")
    out = io.BytesIO()
    thumb.save(out, format="JPEG", quality=80)
    return out.getvalue()


def clean_upload(uploaded_file):
    """Validate type and size; convert HEIC to JPG; build a thumbnail for images."""
    if uploaded_file.size > settings.MAX_UPLOAD_BYTES:
        raise ValidationError("That file is larger than 15 MB. Try a smaller photo or PDF.")
    name = (uploaded_file.name or "").lower()
    extension = name.rsplit(".", 1)[-1] if "." in name else ""
    content = uploaded_file.read()
    kind = sniff(content[:16])
    if kind is None or extension not in ALLOWED_EXTENSIONS:
        raise ValidationError("Upload a PDF, JPG, PNG, or HEIC file.")
    if kind == "pdf":
        return CleanUpload(content, "pdf", "application/pdf", None)
    try:
        image = Image.open(io.BytesIO(content))
        image = ImageOps.exif_transpose(image)
    except Exception as exc:
        raise ValidationError("We couldn't open that image. Try taking the photo again.") from exc
    if kind == "heic":
        out = io.BytesIO()
        image.convert("RGB").save(out, format="JPEG", quality=90)
        content, kind = out.getvalue(), "jpg"
    content_type = "image/png" if kind == "png" else "image/jpeg"
    return CleanUpload(content, kind, content_type, make_thumbnail(image))
