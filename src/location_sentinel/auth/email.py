from __future__ import annotations

import logging

import resend

from ..config import settings

logger = logging.getLogger(__name__)


def send_verification_email(to_email: str, token: str) -> None:
    if not settings.RESEND_API_KEY:
        logger.warning("RESEND_API_KEY not set -- skipping verification email to %s", to_email)
        return

    resend.api_key = settings.RESEND_API_KEY

    # Link goes to the backend API endpoint, which verifies and redirects to FRONTEND_URL/verified.
    base = settings.API_BASE_URL or ""
    verify_url = f"{base}/v1/auth/verify?token={token}"

    resend.Emails.send({
        "from": f"Location Sentinel <noreply@{settings.EMAIL_FROM_DOMAIN}>",
        "to": to_email,
        "subject": "Verify your Location Sentinel account",
        "html": f"""
<p>Welcome to Location Sentinel.</p>
<p><a href="{verify_url}">Click here to verify your email address.</a></p>
<p>This link expires in 24 hours. If you didn't create an account, ignore this email.</p>
""",
    })
