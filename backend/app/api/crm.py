"""CRM & Deal Pipeline API endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Deal, User
from app.schemas import DealIn, DealOut, DealUpdate, PipelineOut
from app.security import get_current_user
from app.services.crm import deals as crm_service
from app.services.crm.excel_sync import MasterExcelSync, trigger_master_excel_sync

router = APIRouter(prefix="/api/crm", tags=["crm"])


@router.get("/pipeline", response_model=PipelineOut)
def get_pipeline(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Retrieve full Kanban pipeline with stage aggregations and revenue forecast."""
    return crm_service.get_pipeline_summary(db)


@router.get("/deals", response_model=list[DealOut])
def list_deals(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List all CRM deals / opportunities."""
    return db.query(Deal).order_by(Deal.id.desc()).all()


@router.post("/deals", response_model=DealOut, status_code=status.HTTP_201_CREATED)
def create_deal(
    deal_in: DealIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create a new CRM deal / opportunity."""
    return crm_service.create_deal(db, deal_in)


@router.patch("/deals/{deal_id}", response_model=DealOut)
def update_deal(
    deal_id: int,
    update: DealUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Update deal stage, value, notes, or expected close date."""
    updated = crm_service.update_deal(db, deal_id, update)
    if not updated:
        raise HTTPException(status_code=404, detail="Deal not found")
    return updated


@router.delete("/deals/{deal_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_deal(
    deal_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Delete a CRM deal."""
    deal = db.query(Deal).filter(Deal.id == deal_id).first()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    db.delete(deal)
    db.commit()
    return None


@router.get("/export-excel")
def export_master_excel(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Download full Multi-Tab Master Excel (.xlsx) CRM workbook."""
    syncer = MasterExcelSync(db)
    xlsx_bytes = syncer.export_excel_bytes()
    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="MASTER_CRM_OPERATIONS.xlsx"'},
    )


@router.get("/export-csv")
def export_master_csv(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Download Master CSV spreadsheet."""
    syncer = MasterExcelSync(db)
    csv_str = syncer.export_master_csv_string()
    return Response(
        content=csv_str,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="MASTER_CRM_OPERATIONS.csv"'},
    )


@router.post("/sync-excel")
def sync_master_excel(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Force an immediate full sync of the Master Excel (.xlsx) and CSV files to disk."""
    excel_path, csv_path = trigger_master_excel_sync(db)
    return {"status": "synced", "excel_path": excel_path, "csv_path": csv_path}

