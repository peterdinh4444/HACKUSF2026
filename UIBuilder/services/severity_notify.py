"""
Email user when dashboard/home threat tier worsens (opt-in only).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from services.auth_db import get_user_for_severity_notify, update_severity_notify_state
from services.smtp_mail import send_severity_increase_email, smtp_configured

_TIER_RANK = {"low": 0, "elevated": 1, "high": 2, "extreme": 3}
_THROTTLE = timedelta(minutes=45)


def _rank(tier: str) -> int | None:
    k = (tier or "").strip().lower()
    if k not in _TIER_RANK:
        return None
    return _TIER_RANK[k]


def process_severity_change(user_id: int, current_tier: str, score) -> None:
    """
    If user opted in and verified email: on first tier sample store baseline;
    if tier rank increases, send one email (throttled). If tier improves, reset baseline.
    """
    if not smtp_configured():
        return
    row = get_user_for_severity_notify(user_id)
    if not row:
        return
    if not int(row.get("alert_email_opt_in") or 0):
        return
    email = (row.get("email") or "").strip()
    if not email or not int(row.get("email_verified") or 0):
        return

    cr = _rank(current_tier)
    if cr is None:
        return

    snap = row.get("severity_snapshot_tier")
    snap = snap.strip().lower() if isinstance(snap, str) and snap.strip() else None
    last_sent = row.get("severity_alert_last_sent_at")

    username = str(row.get("username") or "")

    tier_norm = current_tier.strip().lower()

    if snap is None:
        update_severity_notify_state(user_id, tier_norm, mode="baseline")
        return

    lr = _rank(snap)
    if lr is None:
        update_severity_notify_state(user_id, tier_norm, mode="baseline")
        return

    if cr > lr:
        now = datetime.now(timezone.utc)
        throttled = False
        if last_sent:
            try:
                prev = datetime.fromisoformat(last_sent.replace("Z", "+00:00"))
                if now - prev < _THROTTLE:
                    throttled = True
            except ValueError:
                pass
        if not throttled:
            score_disp = score if score is not None else "—"
            ok, _ = send_severity_increase_email(
                email,
                username=username,
                old_tier=snap,
                new_tier=tier_norm,
                score_display=str(score_disp),
            )
            if ok:
                update_severity_notify_state(user_id, tier_norm, mode="after_email")
                return
            return
        update_severity_notify_state(user_id, tier_norm, mode="tier_only")
        return

    if cr < lr:
        update_severity_notify_state(user_id, tier_norm, mode="baseline")
        return
