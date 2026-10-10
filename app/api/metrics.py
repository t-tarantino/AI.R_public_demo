"""One parameterised endpoint over the compositional derive engine.

    GET /api/metrics/{metric}?start=&end=&group_by=&compare=&scope_*=

- no group_by            -> scalar  {value}
- group_by=day|week|month|quarter|year -> time series
- group_by=location|worker|... -> dimension series (metric-dependent)
- compare=true (scalar)  -> {current, previous, delta, pct_change}
"""
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.db.models import Color, Composition, Location, Party, RequiredItem, User
from app.db.session import get_db
from app.services import derive

router = APIRouter(prefix="/api/metrics", tags=["metrics"])


def _fmt(value, kind: str):
    if value is None:
        return None
    if kind == "count":
        return int(value)
    if kind == "hours":
        return round(float(value), 1)
    return round(float(value), 2)  # money / ratio


def _labels(db: Session, dim: str, keys: list) -> dict:
    ids = [k for k in keys if isinstance(k, int)]
    if dim in ("worker", "customer", "payee"):
        rows = db.query(Party.party_id, Party.name).filter(Party.party_id.in_(ids)).all()
    elif dim == "location":
        rows = db.query(Location.location_id, Location.name).filter(Location.location_id.in_(ids)).all()
    elif dim == "composition":
        rows = db.query(Composition.composition_id, Composition.name).filter(Composition.composition_id.in_(ids)).all()
    elif dim == "color":
        rows = db.query(Color.color_id, Color.name).filter(Color.color_id.in_(ids)).all()
    elif dim == "material":
        rows = db.query(RequiredItem.required_item_id, RequiredItem.name).filter(RequiredItem.required_item_id.in_(ids)).all()
    else:
        return {}
    return {i: n for i, n in rows}


@router.get("/{metric}")
def get_metric(
    metric: str,
    start: date = Query(...),
    end: date = Query(...),
    group_by: str | None = Query(default=None),
    compare: bool = Query(default=False),
    scope_location: list[int] = Query(default=[]),
    scope_worker: list[int] = Query(default=[]),
    scope_customer: list[int] = Query(default=[]),
    scope_payee: list[int] = Query(default=[]),
    scope_composition: list[int] = Query(default=[]),
    scope_color: list[int] = Query(default=[]),
    scope_material: list[int] = Query(default=[]),
    db: Session = Depends(get_db),
    _u: User = Depends(get_current_user),
):
    if metric not in derive.ALL_METRICS:
        raise HTTPException(status_code=404, detail=f"Unknown metric: {metric}")
    kind = derive.ALL_METRICS[metric]

    # Build scope (lists of ids), keeping only dims the (base) metric supports.
    raw = {"location": scope_location, "worker": scope_worker,
           "customer": scope_customer, "payee": scope_payee,
           "composition": scope_composition, "color": scope_color,
           "material": scope_material}
    raw = {k: v for k, v in raw.items() if v}
    scope = None
    if metric in derive.BASE:
        allowed = derive.BASE[metric].dims
        scope = {k: v for k, v in raw.items() if k in allowed} or None

    period = {"start": start.isoformat(), "end": end.isoformat()}

    try:
        if compare and not group_by:
            c = derive.compare(db, metric, start, end, scope)
            return {
                "metric": metric, "kind": kind, "period": period,
                "current": _fmt(c["current"], kind), "previous": _fmt(c["previous"], kind),
                "delta": _fmt(c["delta"], kind), "pct_change": c["pct_change"],
                "previous_period": c["previous_period"],
            }
        result = derive.evaluate(db, metric, start, end, group_by, scope)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if group_by is None:
        return {"metric": metric, "kind": kind, "period": period, "value": _fmt(result, kind)}

    is_time = group_by in derive.TIME_GRANS
    labels = {} if is_time else _labels(db, group_by, list(result.keys()))
    series = [
        {"key": k, "label": (k if is_time else labels.get(k, f"#{k}" if k is not None else "—")),
         "value": _fmt(v, kind)}
        for k, v in result.items()
    ]
    series.sort(key=lambda r: (r["key"] is None, str(r["key"]) if is_time else str(r["label"]).lower()))
    return {"metric": metric, "kind": kind, "group_by": group_by, "period": period, "series": series}
