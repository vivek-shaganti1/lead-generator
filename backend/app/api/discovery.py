from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import DiscoveryRun, User
from app.schemas import DiscoveryRequest, DiscoveryRunOut
from app.security import get_current_user
from app.services.discovery.base import SearchArea
from app.services.discovery.categories import CATEGORY_PRESETS, resolve
from app.services.pipeline import run_discovery

router = APIRouter(prefix="/api/discovery", tags=["discovery"])


@router.get("/categories")
def categories(_: User = Depends(get_current_user)) -> list[dict]:
    return [
        {"key": key, "label": preset["label"], "google_supported": bool(preset["google"])}
        for key, preset in sorted(CATEGORY_PRESETS.items(), key=lambda kv: kv[1]["label"])
    ]


@router.post("/run")
def start_discovery(
    payload: DiscoveryRequest,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    try:
        payload.validate_scope()
        categories_list = resolve(payload.categories)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    area = SearchArea(
        label=payload.label,
        area_name=payload.area_name,
        country_code=payload.country_code,
        **(payload.bbox.model_dump() if payload.bbox else {}),
    )
    try:
        area.validate()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if payload.run_async:
        from app.workers.tasks import discovery_run

        task = discovery_run.delay(
            area={
                "label": area.label, "south": area.south, "west": area.west,
                "north": area.north, "east": area.east, "area_name": area.area_name,
                "country_code": area.country_code,
            },
            categories=categories_list,
            limit=payload.limit,
            use_google_fallback=payload.use_google_fallback,
        )
        return {"queued": True, "task_id": task.id, "area": area.label}

    run = run_discovery(
        db, area=area, categories=categories_list, limit=payload.limit,
        use_google_fallback=payload.use_google_fallback,
    )
    db.commit()
    return {"queued": False, "run": DiscoveryRunOut.model_validate(run).model_dump(mode="json")}


@router.get("/runs", response_model=list[DiscoveryRunOut])
def list_runs(
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    return list(
        db.execute(
            select(DiscoveryRun).order_by(DiscoveryRun.id.desc()).limit(limit)
        ).scalars().all()
    )


@router.get("/runs/{run_id}", response_model=DiscoveryRunOut)
def get_run(run_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    run = db.get(DiscoveryRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Discovery run not found")
    return run
