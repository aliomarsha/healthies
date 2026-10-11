"""Runs the long-term risk profile outside the request that submitted the assessment, so a slow
or failing external model never delays or breaks the care journey."""
from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config
from ..db import SessionLocal
from ..models import Assessment, RiskProfileRecord
from ..risk.prompt import PROMPT_VERSION
from ..risk.service import generate_risk_profile
from .core import audit, now
from .journey import iso

log = logging.getLogger("healthies.risk")


def create_pending(db: Session, a: Assessment, requested_by: str, backend: Optional[str] = None) -> Optional[RiskProfileRecord]:
    name = (backend or config.RISK_BACKEND).lower()
    if name == "off" or a.status != "submitted":
        return None
    rec = RiskProfileRecord(assessment_id=a.id, participant_id=a.participant_id, status="pending", backend=name,
                            prompt_version=PROMPT_VERSION, language=a.participant.language,
                            requested_by=requested_by, created_at=now(db))
    db.add(rec)
    db.flush()
    return rec


def complete(db: Session, rec: RiskProfileRecord) -> RiskProfileRecord:
    a = db.get(Assessment, rec.assessment_id)
    result = generate_risk_profile(a.answers or {}, a.participant, rec.language, backend=rec.backend)
    rec.status = result.status
    rec.model = result.model
    rec.mode = result.mode
    rec.is_fixture = result.is_fixture
    rec.sent_payload = result.payload
    rec.error = result.error
    rec.dropped_items = result.dropped_items
    if result.profile:
        rec.tier = result.profile.estimated_risk_tier
        rec.non_modifiable = result.profile.non_modifiable_historical_factors
        rec.modifiable = result.profile.modifiable_lifestyle_factors
        rec.recommendations = result.profile.clinical_screening_recommendations
    rec.completed_at = now(db)
    audit(db, "system", "system", "risk_profile_" + result.status, "risk_profile", rec.id, rec.participant_id,
          backend=rec.backend, model=rec.model, mode=rec.mode, dropped=len(result.dropped_items))
    return rec


def run_in_background(record_id: int) -> None:
    """Entry point for FastAPI BackgroundTasks (own DB session)."""
    db = SessionLocal()
    try:
        rec = db.get(RiskProfileRecord, record_id)
        if rec and rec.status == "pending":
            complete(db, rec)
            db.commit()
    except Exception:  # pragma: no cover - never let this crash the worker
        log.exception("risk profile background run failed")
        db.rollback()
    finally:
        db.close()


def latest_for(db: Session, assessment: Optional[Assessment]) -> Optional[RiskProfileRecord]:
    if not assessment:
        return None
    return db.scalar(select(RiskProfileRecord).where(RiskProfileRecord.assessment_id == assessment.id)
                     .order_by(RiskProfileRecord.id.desc()).limit(1))


def ser_risk(rec: Optional[RiskProfileRecord], *, staff: bool) -> Optional[dict[str, Any]]:
    if not rec:
        return None
    d: dict[str, Any] = {
        "id": rec.id,
        "status": rec.status,
        "is_fixture": rec.is_fixture,
        "language": rec.language,
        "created_at": iso(rec.created_at),
        "completed_at": iso(rec.completed_at),
    }
    if rec.status == "ok":
        d.update(estimated_risk_tier=rec.tier, non_modifiable_historical_factors=rec.non_modifiable,
                 modifiable_lifestyle_factors=rec.modifiable, clinical_screening_recommendations=rec.recommendations)
    if staff:
        d.update(backend=rec.backend, model=rec.model, mode=rec.mode, prompt_version=rec.prompt_version,
                 sent_payload=rec.sent_payload, dropped_items=rec.dropped_items, error=rec.error,
                 requested_by=rec.requested_by)
    return d
