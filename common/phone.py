import re


class InvalidPhone(ValueError):
    pass


def normalize_phone(raw):
    """Return a US phone number in E.164 form (+1XXXXXXXXXX)."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10 or digits[0] in "01":
        raise InvalidPhone("Enter a 10-digit US phone number.")
    return f"+1{digits}"


def format_phone(e164):
    digits = (e164 or "")[-10:]
    if len(digits) != 10:
        return e164 or ""
    return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
