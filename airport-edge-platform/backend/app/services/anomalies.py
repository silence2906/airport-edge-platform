"""Create durable anomaly events and write structured audit log entries."""

import logging
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models import AirportEvent, utc_now
from app.services.models import AnomalyDetector, MockAnomalyDetector

logger = logging.getLogger("airport_edge.audit")


class AnomalyService:
    """Normalize candidate anomalies and persist them as airport events."""

    def __init__(self, detector: AnomalyDetector | None = None) -> None:
        """Use the supplied detector, or the pass-through mock implementation."""

        self.detector = detector or MockAnomalyDetector()

    def create(
        self,
        db: Session,
        *,
        event_type: str,
        severity: str,
        source: str,
        description: str,
        confidence: float | None = None,
        passenger_id: str | None = None,
        status: str = "REQUIRES_MANUAL_REVIEW",
        details: dict | None = None,
    ) -> AirportEvent:
        """Persist a normalized event and return the refreshed database record."""

        normalized = self.detector.analyze({
            "event_type": event_type,
            "severity": severity,
            "source": source,
            "description": description,
            "confidence": confidence,
            "passenger_id": passenger_id,
            "status": status,
            "details": details or {},
        })
        event = AirportEvent(
            event_id=f"EVT-{uuid4().hex[:12].upper()}",
            timestamp=utc_now(),
            **normalized,
        )
        db.add(event)
        db.commit()
        db.refresh(event)
        logger.info("event_created", extra={
            "event_id": event.event_id,
            "event_type": event.event_type,
            "severity": event.severity,
            "source": event.source,
        })
        return event


anomaly_service = AnomalyService()
