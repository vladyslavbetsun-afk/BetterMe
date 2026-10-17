"""Shared web plumbing: who is signed in, route guards, template rendering."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

import config
import db

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

ALL = ("owner", "viewer", "finance", "designer")
STAFF = ("owner", "viewer")
MONEY = ("owner", "finance")


@dataclass
class User:
    email: str
    role: str | None
    person_id: str | None = None
    name: str | None = None

    @property
    def is_owner(self) -> bool:
        return self.role == "owner"

    @property
    def sees_money(self) -> bool:
        return self.role in MONEY


def current_user(request: Request) -> User:
    """The platform puts the signed-in BetterMe email in X-Auth-Request-Email (spec 05 §5)."""
    email = (request.headers.get("x-auth-request-email") or config.DEV_USER_EMAIL or "").strip().lower()
    if not email:
        return User("", None)
    p = db.one("select id, display_name, app_role from people where lower(email) = %s and active", (email,))
    role = "owner" if email in config.OWNER_EMAILS else (p["app_role"] if p else None)
    return User(email, role, p["id"] if p else None, p["display_name"] if p else email)


def require(*roles: str):
    def dep(request: Request) -> User:
        u = current_user(request)
        if u.role not in roles:
            raise HTTPException(403, f"{u.email or 'Anonymous'} can't open this page")
        return u
    return dep


def actor(u: User) -> str:
    return u.email or "unknown"


# --- template filters -------------------------------------------------------------------------

def ago(t: datetime | None) -> str:
    if not t:
        return "—"
    s = (datetime.now(config.TZ) - t).total_seconds()
    if s < 3600:
        return f"{max(1, round(s / 60))}m ago"
    if s < 86400:
        return f"{round(s / 3600)}h ago"
    return f"{int(s // 86400)}d ago"


def when(t: datetime | date | None, fmt: str = "%a %d %b %H:%M") -> str:
    if not t:
        return "—"
    if isinstance(t, datetime):
        return t.astimezone(config.TZ).strftime(fmt)
    return t.strftime("%a %d %b" if fmt == "%a %d %b %H:%M" else fmt)


def bdays(n: float | None) -> str:
    if n is None:
        return "—"
    n = max(0, n)
    w = int(n) if n >= 1 else round(n, 1)
    return f"{w:g} business day{'' if w == 1 else 's'}"


def num(n, digits: int = 1) -> str:
    if n is None:
        return "—"
    if isinstance(n, int | Decimal) and n == int(n):
        return f"{int(n):,}"
    return f"{float(n):,.{digits}f}"


def usd(lo, hi=None) -> str:
    if lo is None:
        return "—"
    hi = lo if hi is None else hi
    f = (lambda x: f"${x:,.0f}") if Decimal(lo) == int(lo) and Decimal(hi) == int(hi) else (lambda x: f"${x:,.2f}")
    return f(lo) if Decimal(lo) == Decimal(hi) else f"{f(lo)}–{f(hi)[1:]}"


templates.env.filters.update(ago=ago, when=when, bdays=bdays, num=num, usd=usd)
templates.env.globals.update(ticket_url=config.ticket_url)
templates.env.policies["json.dumps_kwargs"] = {"default": str}


def render(request: Request, name: str, user: User, **ctx) -> HTMLResponse:
    from core import scheduler

    nav = [("Flow", "/flow", STAFF), ("Pipeline", "/pipeline", STAFF), ("Assign", "/assign", STAFF),
           ("Review", "/review", STAFF), ("Load", "/load", STAFF), ("Publish", "/publish", STAFF),
           ("Report", "/report", STAFF), ("Spend", "/spend", MONEY), ("Performance", "/performance", STAFF),
           ("Intake", "/intake", STAFF), ("Images", "/images", ALL), ("Admin", "/admin", ("owner",))]
    return templates.TemplateResponse(request, name, {
        "user": user, "nav": [(lbl, href) for lbl, href, roles in nav if user.role in roles],
        "path": request.url.path, "health": scheduler.health() if user.role in STAFF else [],
        "flags": {k: db.flag(k) for k in ("jira_writes_enabled", "slack_send_enabled", "notion_writes_enabled",
                                           "review_automation_enabled")},
        "flash": request.query_params.get("msg"), **ctx})


def back(path: str, msg: str | None = None) -> RedirectResponse:
    from urllib.parse import quote

    return RedirectResponse(path + (("&" if "?" in path else "?") + "msg=" + quote(msg) if msg else ""), 303)
