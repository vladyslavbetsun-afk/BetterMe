"""Slack: deep links for drafts (decision (a), spec 05 §3) and an optional bot post into #bp-ops (decision (b))."""

import os

import httpx

import config


def bot_configured() -> bool:
    return bool(os.environ.get("SLACK_BOT_TOKEN") and os.environ.get("SLACK_OPS_CHANNEL"))


def dm_link(user_id: str | None) -> str | None:
    """Open a DM with this person in Slack. Vladyslav sends the drafted text himself."""
    if not user_id:
        return None
    if config.SLACK_TEAM_ID:
        return f"https://app.slack.com/client/{config.SLACK_TEAM_ID}/{user_id}"
    return f"https://slack.com/app_redirect?channel={user_id}"


def post(channel: str, text: str) -> str:
    """Post as the bot. Returns the message ts. Only called from core/outbound.py."""
    token = os.environ.get("SLACK_BOT_TOKEN")
    if not token:
        raise RuntimeError("Slack bot is not configured")
    r = httpx.post("https://slack.com/api/chat.postMessage", headers={"Authorization": f"Bearer {token}"},
                   json={"channel": channel, "text": text, "unfurl_links": False}, timeout=30)
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"Slack error: {data.get('error')}")
    return data["ts"]


def mrkdwn_list(items: list[tuple[str, str]]) -> str:
    """Bullet lines in Slack link syntax: • <url|text>."""
    return "\n".join(f"• <{url}|{text}>" for url, text in items)
