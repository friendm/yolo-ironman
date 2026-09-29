"""Render simple sample documents (PNG) for demos and tests. Clearly marked as samples."""

import io

from PIL import Image, ImageDraw, ImageFont


def _font(size):
    for name in ("DejaVuSans.ttf", "Arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def render(title, lines, width=1100):
    height = 220 + 48 * len(lines)
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 0, width, 90], fill=(10, 37, 64))
    draw.text((40, 26), title, fill="white", font=_font(34))
    y = 130
    for label, value in lines:
        draw.text((40, y), f"{label}:", fill=(66, 84, 102), font=_font(24))
        draw.text((420, y), str(value), fill=(10, 37, 64), font=_font(24))
        y += 48
    draw.text((40, height - 60), "SAMPLE DOCUMENT - NOT VALID FOR COVERAGE", fill=(198, 40, 40), font=_font(22))
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def coi(
    business,
    insurer="Peachtree Mutual Insurance Co.",
    start="2026-01-15",
    end="2027-01-15",
    occurrence=1_000_000,
    aggregate=2_000_000,
    auto=1_000_000,
    holder="Certificate holder on file",
):
    return render(
        "CERTIFICATE OF LIABILITY INSURANCE",
        [
            ("Insured", business),
            ("Insurer A", insurer),
            ("NAIC #", "12345"),
            ("GL policy number", "GL-2026-000123"),
            ("Policy effective", start),
            ("Policy expiration", end),
            ("Each occurrence", f"${occurrence:,}"),
            ("General aggregate", f"${aggregate:,}"),
            ("Auto combined single limit", f"${auto:,}" if auto else "None"),
            ("Workers comp", "Yes"),
            ("Certificate holder", holder),
        ],
    )


def permit(kind, business, authority, number, issued="2026-03-01", expires="2027-02-28"):
    return render(
        kind.upper(),
        [("Holder", business), ("Issued by", authority), ("Number", number), ("Issued", issued), ("Expires", expires)],
    )
