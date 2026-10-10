"""BOM endpoints: read/replace the requirements of a composition."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.db.models import Composition, Requirement, User
from app.db.session import get_db
from app.schemas.master import BomLine, BomLineRead
from app.services.audit import log_action

router = APIRouter(prefix="/api/composition", tags=["bom"])


def _get_composition(db: Session, composition_id: int) -> Composition:
    comp = db.get(Composition, composition_id)
    if comp is None:
        raise HTTPException(status_code=404, detail=f"Composition {composition_id} not found")
    return comp


@router.get("/{composition_id}/bom", response_model=list[BomLineRead])
def get_bom(
    composition_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    comp = _get_composition(db, composition_id)
    return comp.requirements


@router.put("/{composition_id}/bom", response_model=list[BomLineRead])
def replace_bom(
    composition_id: int,
    lines: list[BomLine],
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Replace the full requirements list of a composition (BOM editor saves
    the whole table at once — simplest correct semantics)."""
    comp = _get_composition(db, composition_id)

    item_ids = [line.required_item_id for line in lines]
    if len(item_ids) != len(set(item_ids)):
        raise HTTPException(
            status_code=400,
            detail="The same material appears twice in the BOM.")

    before = {r.required_item_id: str(r.quantity) for r in comp.requirements}
    comp.requirements.clear()          # delete-orphan removes old rows
    db.flush()
    for line in lines:
        comp.requirements.append(Requirement(
            required_item_id=line.required_item_id,
            quantity=line.quantity,
            comment=line.comment))
    db.flush()
    after = {line.required_item_id: str(line.quantity) for line in lines}
    log_action(db, user, "update", "composition_bom", composition_id,
               {"da": before, "a": after})
    db.commit()
    db.refresh(comp)
    return comp.requirements