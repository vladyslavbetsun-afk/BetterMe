"""Performance (spec 01) and Intake (spec 02) are Phase 4. Until then these pages show what's already imported."""

from fastapi import APIRouter, Depends, Request

import db
from web import STAFF, User, render, require

router = APIRouter()


@router.get("/performance")
def performance(request: Request, u: User = Depends(require(*STAFF))):
    week = db.scalar("select max(week) from ahrefs_page_weekly")
    rows = db.query("select a.url, a.cohort, a.slipped_level, w.traffic, w.keywords, w.top3, w.top4_10, c.ai_all, c.aio, "
                    "c.chatgpt, c.perplexity from articles a left join ahrefs_page_weekly w on w.url = a.url and w.week = %s "
                    "left join ai_citations_weekly c on c.target = a.url and c.mode = 'exact' and c.week = %s "
                    "order by w.traffic desc nulls last, a.url", (week, week))
    return render(request, "performance.html", u, rows=rows, week=week)


@router.get("/intake")
def intake(request: Request, u: User = Depends(require(*STAFF))):
    return render(request, "intake.html", u)
