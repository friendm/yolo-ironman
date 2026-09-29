"""Message templates. Every message carries a link back to the relevant page."""

SMS = {
    "otp": "{code} is your {site} login code. It expires in 10 minutes.",
    "event_invite": "{org} invited you to {event} on {site}. Join here: {link}",
    "document_verified": "Your {document} is verified. {link}",
    "document_rejected": "Your {document} was not accepted: {reason} Upload a new one: {link}",
    "document_expiring": "Your {document} expires {date}. Upload the new one: {link}",
    "bulk_reminder": "{org} needs these for {event}: {missing}. Update here: {link}",
}

EMAIL = {
    "vendor_red": (
        "{vendor} is not ready for {event}",
        "{vendor} is now red for {event} ({date}).\n\nReasons:\n{reasons}\n\nView the vendor: {link}\n",
    ),
    "ai_request": (
        "Additional insured certificate request: {vendor} for {event}",
        "Hello {agent},\n\n{vendor} is working {event} ({dates}) and needs a certificate of insurance "
        "naming the following as additional insured, exactly as written:\n\n{wording}\n\n"
        "Please upload the certificate here (no account needed; link valid 30 days):\n{link}\n\n"
        "Thank you,\n{site}\n",
    ),
    "agent_verify": (
        "Please confirm active coverage for {vendor}",
        "Hello {agent},\n\nWe are verifying the certificate of insurance for {vendor}. Please reply to "
        "confirm the policy below is active with these limits and dates:\n\n{summary}\n\nThank you,\n{site}\n",
    ),
    "admin_digest": (
        "{count} documents waiting for verification",
        "{count} documents are pending verification.\n\nOpen the queue: {link}\n",
    ),
    "magic_link": (
        "Your {site} sign-in link",
        "Use this link to sign in. It expires in 15 minutes and works once.\n\n{link}\n",
    ),
}


def render_sms(template, payload):
    return SMS[template].format(**payload)


def render_email(template, payload):
    subject, body = EMAIL[template]
    return subject.format(**payload), body.format(**payload)
