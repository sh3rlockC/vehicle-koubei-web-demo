from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.schemas import VehicleResolveRequest, VehicleResolveResponse
from app.services.passphrase import require_passphrase_session
from app.services.vehicle_resolver import VehicleResolver

router = APIRouter(prefix="/api/vehicles", tags=["vehicles"])


@router.post("/resolve", response_model=VehicleResolveResponse)
def resolve_vehicle(
    payload: VehicleResolveRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> VehicleResolveResponse:
    require_passphrase_session(request, settings)
    resolver = VehicleResolver(db=db, settings=settings)
    try:
        result = resolver.resolve(payload.query)
    except (RuntimeError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return VehicleResolveResponse.model_validate(result)
