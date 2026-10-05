"""Persist a compact audit record for each processed device scan."""

from uuid import uuid4

from sqlalchemy.orm import Session

from app.models import ScanRecord, utc_now


def record_scan(
    db: Session,
    *,
    scan_type: str,
    device_id: str,
    passenger_id: str | None,
    anomaly_detected: bool,
) -> None:
    """Create and commit one scan record with its device and anomaly outcome."""

    db.add(ScanRecord(
        scan_id=f"SCN-{uuid4().hex[:12].upper()}",
        scan_type=scan_type,
        device_id=device_id,
        passenger_id=passenger_id,
        timestamp=utc_now(),
        anomaly_detected=anomaly_detected,
    ))
    db.commit()
