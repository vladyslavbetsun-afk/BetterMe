from fastapi import APIRouter, Depends, Request

from modules.load import service
from web import STAFF, User, render, require

router = APIRouter()


@router.get("/load")
def load(request: Request, u: User = Depends(require(*STAFF))):
    return render(request, "load.html", u, v=service.view(with_money=u.sees_money))
