"""Transactional email — account verification + password reset.

Backends (``EMAIL_BACKEND``):
  * ``console`` (default) — log the rendered message + link. No SMTP needed, so
    local dev and tests work out of the box and the link is visible in the log.
  * ``smtp`` — deliver via the ``SMTP_*`` settings using the stdlib ``smtplib``
    in a worker thread. Sending is rare (register / forgot-password), so a
    ``to_thread`` hop keeps the async surface without pulling in another dep.

Delivery failures are swallowed (logged, not raised): a flaky mail server must
never turn a registration into a 500. The user can always re-request the link.
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
from email.message import EmailMessage

from app.core.config import settings

logger = logging.getLogger(__name__)


def _send_smtp(msg: EmailMessage) -> None:
    if settings.SMTP_SSL:
        with smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as server:
            if settings.SMTP_USER:
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.send_message(msg)
        return
    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as server:
        server.ehlo()
        if settings.SMTP_STARTTLS:
            server.starttls()
            server.ehlo()
        if settings.SMTP_USER:
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        server.send_message(msg)


async def send_email(to: str, subject: str, html: str, text: str) -> None:
    """Send one email; logs to console unless EMAIL_BACKEND=smtp and a host is set."""
    if settings.EMAIL_BACKEND != "smtp" or not settings.SMTP_HOST:
        logger.info("[email:console] to=%s | subject=%s\n%s", to, subject, text)
        return

    msg = EmailMessage()
    msg["From"] = settings.EMAIL_FROM
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    try:
        await asyncio.to_thread(_send_smtp, msg)
        logger.info("Sent %r email to %s", subject, to)
    except Exception:
        logger.exception("Failed to send %r email to %s", subject, to)


# ── Templates ────────────────────────────────────────────────────────────────
def _link(path: str, token: str) -> str:
    return f"{settings.FRONTEND_BASE_URL.rstrip('/')}{path}?token={token}"


def _layout(heading: str, intro: str, button: str, link: str, footnote: str) -> str:
    return f"""\
<!doctype html><html><body style="margin:0;background:#f4f4f5;padding:32px 0;
  font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#18181b">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center">
    <table role="presentation" width="440" cellpadding="0" cellspacing="0"
      style="background:#ffffff;border-radius:12px;padding:32px;border:1px solid #e4e4e7">
      <tr><td style="font-size:22px;font-weight:700;padding-bottom:8px">
        Penguin<span style="color:#0ea5e9">AI</span></td></tr>
      <tr><td style="font-size:18px;font-weight:600;padding:8px 0">{heading}</td></tr>
      <tr><td style="font-size:14px;line-height:1.6;color:#3f3f46;padding-bottom:20px">{intro}</td></tr>
      <tr><td style="padding-bottom:20px">
        <a href="{link}" style="display:inline-block;background:#0ea5e9;color:#ffffff;
          text-decoration:none;font-size:14px;font-weight:600;padding:11px 22px;border-radius:8px">
          {button}</a></td></tr>
      <tr><td style="font-size:12px;color:#71717a;line-height:1.6;padding-bottom:4px">
        Or paste this link into your browser:<br>
        <a href="{link}" style="color:#0ea5e9;word-break:break-all">{link}</a></td></tr>
      <tr><td style="font-size:12px;color:#a1a1aa;padding-top:16px;
        border-top:1px solid #f4f4f5">{footnote}</td></tr>
    </table>
    <div style="font-size:11px;color:#a1a1aa;padding-top:16px">
      PenguinAI · AI signal platform · No trading execution</div>
  </td></tr></table>
</body></html>"""


async def send_verification_email(to: str, token: str) -> None:
    link = _link("/auth/verify-email", token)
    subject = "Verify your PenguinAI email"
    text = (
        "Welcome to PenguinAI!\n\n"
        f"Confirm your email address:\n{link}\n\n"
        "This link expires in 24 hours. If you didn't create an account, ignore this email."
    )
    html = _layout(
        "Confirm your email",
        "Thanks for signing up. Confirm your email address to activate your account.",
        "Verify email",
        link,
        "This link expires in 24 hours. If you didn't sign up, you can safely ignore this email.",
    )
    await send_email(to, subject, html, text)


async def send_password_reset_email(to: str, token: str) -> None:
    link = _link("/auth/reset-password", token)
    subject = "Reset your PenguinAI password"
    text = (
        "We received a request to reset your PenguinAI password.\n\n"
        f"Reset it here:\n{link}\n\n"
        "This link expires in 1 hour. If you didn't request this, ignore this email."
    )
    html = _layout(
        "Reset your password",
        "We received a request to reset your password. Click below to choose a new one.",
        "Reset password",
        link,
        "This link expires in 1 hour. If you didn't request a reset, you can safely ignore this email.",
    )
    await send_email(to, subject, html, text)
