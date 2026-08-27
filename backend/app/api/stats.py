from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Event, User
from app.schemas import ORMModel
from app.security import get_current_user
from app.services import stats as stats_service

router = APIRouter(prefix="/api/stats", tags=["stats"])


class EventOut(ORMModel):
    id: int
    type: str
    lead_id: int | None = None
    payload: dict
    created_at: object


@router.get("/dashboard")
def dashboard(
    days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    return stats_service.dashboard(db, days=days)


@router.get("/timeseries")
def timeseries(
    days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    return stats_service.timeseries(db, days=days)


@router.get("/today")
def today(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return stats_service.today_snapshot(db)


@router.post("/rollup")
def rollup(
    days: int = Query(default=7, ge=1, le=90),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    rows = stats_service.rollup_range(db, days=days)
    db.commit()
    return {"days_rolled": len(rows)}


@router.get("/events")
def events(
    limit: int = Query(default=100, ge=1, le=500),
    type: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    query = select(Event).order_by(Event.id.desc()).limit(limit)
    if type:
        query = query.where(Event.type == type)
    return [
        {
            "id": e.id, "type": e.type, "lead_id": e.lead_id,
            "payload": e.payload, "created_at": e.created_at.isoformat(),
        }
        for e in db.execute(query).scalars().all()
    ]
