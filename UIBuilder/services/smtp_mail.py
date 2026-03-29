"""
Send transactional email via SMTP (e.g. Gmail with an app password).
"""
from __future__ import annotations

import html
import os
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr


def _mail_password() -> str:
    raw = (os.environ.get("MAIL_PASSWORD") or "").strip()
    return re.sub(r"\s+", "", raw)


def smtp_configured() -> bool:
    user = (os.environ.get("MAIL_USERNAME") or "").strip()
    return bool(user and _mail_password())


def _from_header() -> str:
    mail_user = (os.environ.get("MAIL_USERNAME") or "").strip()
    sender = (os.environ.get("MAIL_DEFAULT_SENDER") or mail_user).strip()
    name = (os.environ.get("MAIL_FROM_NAME") or "Hurricane Hub").strip()
    if name and sender:
        return formataddr((name, sender))
    return sender or mail_user


def _verification_bodies(code: str, username: str, *, for_signup: bool) -> tuple[str, str]:
    """Plain text + HTML (inline styles for mail clients)."""
    safe_code = html.escape((code or "").strip(), quote=True)
    safe_name = html.escape((username or "").strip() or "there", quote=True)
    plain_greet = f"Hi {username},\n\n" if (username or "").strip() else "Hi,\n\n"
    if for_signup:
        plain = (
            f"{plain_greet}"
            f"Welcome to Hurricane Hub. Your verification code is: {code}\n\n"
            "Enter it on the site to finish creating your account. It expires in 15 minutes.\n"
            "If you did not sign up, you can ignore this email.\n"
        )
        head = "Verify your account"
        sub = "Use this code to finish signing up:"
    else:
        plain = (
            f"{plain_greet}"
            f"Your Hurricane Hub verification code is: {code}\n\n"
            "It expires in 15 minutes. If you did not try to sign in, you can ignore this email.\n"
        )
        head = "Sign-in verification"
        sub = "Use this code to finish signing in:"
    html_body = f"""\
<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8" /><meta name="viewport" content="width=device-width, initial-scale=1" /></head>
<body style="margin:0;padding:0;background-color:#f4f4f5;font-family:'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background-color:#f4f4f5;padding:28px 16px;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" style="max-width:480px;background:#ffffff;border-radius:12px;border:1px solid #e4e4e7;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.04);">
          <tr>
            <td style="padding:24px 28px 8px;background:linear-gradient(135deg,#0a0a0a 0%,#27272a 100%);">
              <p style="margin:0;font-size:11px;letter-spacing:0.12em;text-transform:uppercase;color:#a1a1aa;">Hurricane Hub</p>
              <p style="margin:8px 0 0;font-size:20px;font-weight:600;color:#fafafa;line-height:1.3;">{html.escape(head)}</p>
            </td>
          </tr>
          <tr>
            <td style="padding:24px 28px 8px;">
              <p style="margin:0 0 16px;font-size:15px;line-height:1.55;color:#3f3f46;">Hi {safe_name},</p>
              <p style="margin:0 0 20px;font-size:15px;line-height:1.55;color:#52525b;">{html.escape(sub)}</p>
              <p style="margin:0 0 24px;text-align:center;">
                <span style="display:inline-block;font-family:'IBM Plex Mono',Consolas,monospace;font-size:28px;font-weight:600;letter-spacing:0.35em;padding:16px 24px;background:#fafafa;border:1px solid #e4e4e7;border-radius:10px;color:#0a0a0a;">{safe_code}</span>
              </p>
              <p style="margin:0 0 20px;font-size:13px;line-height:1.5;color:#71717a;">Expires in <strong>15 minutes</strong>. If you didn’t request this, you can ignore this message.</p>
            </td>
          </tr>
          <tr>
            <td style="padding:16px 28px 24px;border-top:1px solid #f4f4f5;">
              <p style="margin:0;font-size:12px;line-height:1.45;color:#a1a1aa;">Planning aid only — not an official weather alert. For warnings, use <a href="https://www.weather.gov/" style="color:#52525b;">weather.gov</a> and your county.</p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""
    return plain, html_body


def send_login_verification_code(
    to_email: str,
    code: str,
    *,
    username: str = "",
    for_signup: bool = False,
) -> tuple[bool, str]:
    """
    Send a short numeric code. Returns (ok, error_message).
    Use for_signup=True right after register; False for first-time sign-in verification.
    """
    to_email = (to_email or "").strip()
    if not to_email:
        return False, "No recipient address"

    if not smtp_configured():
        return False, "Mail is not configured (set MAIL_USERNAME and MAIL_PASSWORD)"

    host = (os.environ.get("MAIL_SERVER") or "smtp.gmail.com").strip()
    try:
        port = int(os.environ.get("MAIL_PORT") or "587")
    except ValueError:
        port = 587
    use_tls = (os.environ.get("MAIL_USE_TLS") or "true").lower() in ("1", "true", "yes")
    mail_user = (os.environ.get("MAIL_USERNAME") or "").strip()
    mail_pw = _mail_password()
    from_header = _from_header()

    subject = "Verify your Hurricane Hub account" if for_signup else "Your Hurricane Hub sign-in code"
    plain_body, html_body = _verification_bodies(code, username, for_signup=for_signup)

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_header
    msg["To"] = to_email
    msg.set_content(plain_body, charset="utf-8")
    msg.add_alternative(html_body, subtype="html", charset="utf-8")

    try:
        if use_tls:
            context = ssl.create_default_context()
            with smtplib.SMTP(host, port, timeout=45) as smtp:
                smtp.ehlo()
                smtp.starttls(context=context)
                smtp.ehlo()
                smtp.login(mail_user, mail_pw)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP_SSL(host, port, timeout=45) as smtp:
                smtp.login(mail_user, mail_pw)
                smtp.send_message(msg)
    except OSError as e:
        return False, str(e) or "Could not reach mail server"
    except smtplib.SMTPAuthenticationError as e:
        err = str(e) or "SMTP authentication failed"
        hint = " For Gmail, use an App Password (Google Account → Security → 2-Step Verification → App passwords), not your normal password."
        return False, err + hint
    except smtplib.SMTPException as e:
        return False, str(e) or "SMTP error"
    return True, ""


def send_evacuation_zone_sample_email(
    to_email: str,
    *,
    username: str = "",
    sample_zone_label: str = "Zone B (example)",
    sample_home_nickname: str = "My Tampa home",
) -> tuple[bool, str]:
    """
    Sample of a future “evacuation status changed” notice (opt-in users with saved homes).
    Plain + HTML; not tied to live county data yet.
    """
    to_email = (to_email or "").strip()
    if not to_email:
        return False, "No recipient address"
    if not smtp_configured():
        return False, "Mail is not configured"

    host = (os.environ.get("MAIL_SERVER") or "smtp.gmail.com").strip()
    try:
        port = int(os.environ.get("MAIL_PORT") or "587")
    except ValueError:
        port = 587
    use_tls = (os.environ.get("MAIL_USE_TLS") or "true").lower() in ("1", "true", "yes")
    mail_user = (os.environ.get("MAIL_USERNAME") or "").strip()
    mail_pw = _mail_password()
    from_header = _from_header()

    safe_name = html.escape((username or "").strip() or "there", quote=True)
    safe_zone = html.escape(sample_zone_label.strip() or "your zone", quote=True)
    safe_home = html.escape(sample_home_nickname.strip() or "a saved home", quote=True)
    greet_plain = f"Hi {username},\n\n" if (username or "").strip() else "Hi,\n\n"
    plain = (
        f"{greet_plain}"
        f"[SAMPLE — not a real alert]\n\n"
        f"We would email you if an evacuation-related status changed for a saved address "
        f"({sample_home_nickname}) — for example if mapping showed {sample_zone_label}.\n\n"
        "This is only a preview of the message style. Always follow NWS, your county, and road officials.\n"
    )
    html_body = f"""\
<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8" /><meta name="viewport" content="width=device-width, initial-scale=1" /></head>
<body style="margin:0;padding:0;background-color:#f4f4f5;font-family:'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background-color:#f4f4f5;padding:28px 16px;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" style="max-width:520px;background:#ffffff;border-radius:12px;border:1px solid #e4e4e7;overflow:hidden;">
          <tr>
            <td style="padding:22px 26px 10px;background:linear-gradient(135deg,#14532d 0%,#166534 100%);">
              <p style="margin:0;font-size:10px;letter-spacing:0.14em;text-transform:uppercase;color:#bbf7d0;">Sample preview</p>
              <p style="margin:8px 0 0;font-size:19px;font-weight:600;color:#fafafa;line-height:1.35;">Evacuation status notice</p>
            </td>
          </tr>
          <tr>
            <td style="padding:22px 26px 12px;">
              <p style="margin:0 0 14px;font-size:15px;line-height:1.55;color:#3f3f46;">Hi {safe_name},</p>
              <p style="margin:0 0 18px;font-size:14px;line-height:1.55;color:#52525b;">
                This is a <strong>test email</strong> showing how Hurricane Hub might alert you if we detect an
                important evacuation-related change for <strong>{safe_home}</strong> (for example zone context like <strong>{safe_zone}</strong>).
              </p>
              <p style="margin:0;font-size:12px;line-height:1.45;color:#71717a;">Always confirm with your county emergency manager and NWS Tampa Bay. You can change email settings anytime under <strong>Alerts &amp; news</strong> in the app.</p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""

    msg = EmailMessage()
    msg["Subject"] = "[Hurricane Hub] Sample: evacuation status email"
    msg["From"] = from_header
    msg["To"] = to_email
    msg.set_content(plain, charset="utf-8")
    msg.add_alternative(html_body, subtype="html", charset="utf-8")

    try:
        if use_tls:
            context = ssl.create_default_context()
            with smtplib.SMTP(host, port, timeout=45) as smtp:
                smtp.ehlo()
                smtp.starttls(context=context)
                smtp.ehlo()
                smtp.login(mail_user, mail_pw)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP_SSL(host, port, timeout=45) as smtp:
                smtp.login(mail_user, mail_pw)
                smtp.send_message(msg)
    except OSError as e:
        return False, str(e) or "Could not reach mail server"
    except smtplib.SMTPException as e:
        return False, str(e) or "SMTP error"
    return True, ""


def send_notification_preferences_confirmation_email(
    to_email: str,
    *,
    username: str = "",
    tier_alerts: bool = False,
    evacuation_alerts: bool = False,
) -> tuple[bool, str]:
    """Sent after the user explicitly saves notification preferences with at least one option on."""
    to_email = (to_email or "").strip()
    if not to_email:
        return False, "No recipient address"
    if not smtp_configured():
        return False, "Mail is not configured"

    host = (os.environ.get("MAIL_SERVER") or "smtp.gmail.com").strip()
    try:
        port = int(os.environ.get("MAIL_PORT") or "587")
    except ValueError:
        port = 587
    use_tls = (os.environ.get("MAIL_USE_TLS") or "true").lower() in ("1", "true", "yes")
    mail_user = (os.environ.get("MAIL_USERNAME") or "").strip()
    mail_pw = _mail_password()
    from_header = _from_header()

    bits = []
    if tier_alerts:
        bits.append("readiness tier increases (low → elevated → high → extreme)")
    if evacuation_alerts:
        bits.append("evacuation-related updates for your saved homes when available")
    summary = "; ".join(bits) if bits else "updates"

    greet = f"Hi {username},\n\n" if (username or "").strip() else "Hi,\n\n"
    plain = (
        f"{greet}"
        f"You turned on Hurricane Hub email notifications for: {summary}.\n\n"
        "These messages are helpers from the app — not official warnings. "
        "Always follow the National Weather Service and your county emergency manager.\n\n"
        "Change or turn off alerts anytime under Alerts & news in the navigation.\n"
    )

    safe_name = html.escape((username or "").strip() or "there", quote=True)
    safe_summary = html.escape(summary, quote=True)
    html_body = f"""\
<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8" /><meta name="viewport" content="width=device-width, initial-scale=1" /></head>
<body style="margin:0;padding:0;background-color:#f4f4f5;font-family:'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background-color:#f4f4f5;padding:28px 16px;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" style="max-width:480px;background:#ffffff;border-radius:12px;border:1px solid #e4e4e7;">
          <tr>
            <td style="padding:24px 26px;">
              <p style="margin:0 0 12px;font-size:15px;line-height:1.55;color:#3f3f46;">Hi {safe_name},</p>
              <p style="margin:0 0 12px;font-size:14px;line-height:1.55;color:#52525b;">
                Your notification preferences are saved. We’ll email you about: <strong>{safe_summary}</strong>.
              </p>
              <p style="margin:0;font-size:12px;line-height:1.45;color:#71717a;">
                Planning aid only — not an official alert. Manage settings anytime under <strong>Alerts &amp; news</strong>.
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""

    msg = EmailMessage()
    msg["Subject"] = "[Hurricane Hub] Notification preferences saved"
    msg["From"] = from_header
    msg["To"] = to_email
    msg.set_content(plain, charset="utf-8")
    msg.add_alternative(html_body, subtype="html", charset="utf-8")

    try:
        if use_tls:
            context = ssl.create_default_context()
            with smtplib.SMTP(host, port, timeout=45) as smtp:
                smtp.ehlo()
                smtp.starttls(context=context)
                smtp.ehlo()
                smtp.login(mail_user, mail_pw)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP_SSL(host, port, timeout=45) as smtp:
                smtp.login(mail_user, mail_pw)
                smtp.send_message(msg)
    except OSError as e:
        return False, str(e) or "Could not reach mail server"
    except smtplib.SMTPException as e:
        return False, str(e) or "SMTP error"
    return True, ""


def send_severity_increase_email(
    to_email: str,
    *,
    username: str = "",
    old_tier: str = "",
    new_tier: str = "",
    score_display: str = "—",
) -> tuple[bool, str]:
    """Notify opt-in users when dashboard-style threat tier worsens."""
    to_email = (to_email or "").strip()
    if not to_email:
        return False, "No recipient address"
    if not smtp_configured():
        return False, "Mail is not configured"

    host = (os.environ.get("MAIL_SERVER") or "smtp.gmail.com").strip()
    try:
        port = int(os.environ.get("MAIL_PORT") or "587")
    except ValueError:
        port = 587
    use_tls = (os.environ.get("MAIL_USE_TLS") or "true").lower() in ("1", "true", "yes")
    mail_user = (os.environ.get("MAIL_USERNAME") or "").strip()
    mail_pw = _mail_password()
    from_header = _from_header()

    greet = f"Hi {username},\n\n" if username else "Hi,\n\n"
    body = (
        f"{greet}"
        f"Hurricane Hub detected a higher readiness tier on your last dashboard check: "
        f"{old_tier} → {new_tier} (score about {score_display}/100).\n\n"
        "This is from public-data feeds in the app — not an official warning. "
        "Check NWS (weather.gov) and your county emergency manager right away.\n\n"
        "You received this because you opted in at sign-up or in dashboard settings.\n"
    )

    msg = EmailMessage()
    msg["Subject"] = f"[Hurricane Hub] Risk tier increased to {new_tier}"
    msg["From"] = from_header
    msg["To"] = to_email
    msg.set_content(body, charset="utf-8")

    try:
        if use_tls:
            context = ssl.create_default_context()
            with smtplib.SMTP(host, port, timeout=45) as smtp:
                smtp.ehlo()
                smtp.starttls(context=context)
                smtp.ehlo()
                smtp.login(mail_user, mail_pw)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP_SSL(host, port, timeout=45) as smtp:
                smtp.login(mail_user, mail_pw)
                smtp.send_message(msg)
    except OSError as e:
        return False, str(e) or "Could not reach mail server"
    except smtplib.SMTPException as e:
        return False, str(e) or "SMTP error"
    return True, ""
