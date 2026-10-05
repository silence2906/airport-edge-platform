"""Versioned REST endpoints for passenger, scanner, device, rules, and event flows."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.events import event_hub
from app.models import AirportEvent, Device, Passenger, ScanRecord, SecurityRule
from app.schemas import (
    AnomalyAnalyzeRequest,
    AssistedCheckinRequest,
    BaggageScanRequest,
    CameraScanRequest,
    DeviceHeartbeat,
    DeviceRegistration,
    EventOut,
    EventStatusUpdate,
    IdentityVerifyRequest,
    PassengerOut,
    RuleInput,
    SelfCheckinRequest,
    ThermalScanRequest,
)
from app.services.anomalies import anomaly_service
from app.services.checkin import complete_self_checkin, verify_identity
from app.services.devices import mark_heartbeat, mark_offline_devices, register_device
from app.services.models import MockThermalAnalyzer, MockVisionModel
from app.services.passengers import find_passenger
from app.services.scans import record_scan
from app.services.rules import configured_temperature_threshold, evaluate_detections, upsert_rule

router = APIRouter(prefix="/api/v1")
vision_model = MockVisionModel()
thermal_analyzer = MockThermalAnalyzer()


async def publish_event(event: AirportEvent) -> None:
    """Broadcast a persisted event using the same response shape as the REST API."""

    await event_hub.publish(EventOut.model_validate(event).model_dump(mode="json"))


def require_passenger(db: Session, passenger_id: str) -> Passenger:
    """Load a passenger profile or return an HTTP 404 response."""

    passenger = find_passenger(db, passenger_id)
    if passenger is None:
        raise HTTPException(status_code=404, detail="Passenger not found")
    return passenger


def require_device(db: Session, device_id: str) -> Device:
    """Load a registered device or return an HTTP 404 response."""

    device = db.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")
    return device


async def publish_device_timeouts(db: Session) -> None:
    """Create and broadcast events for devices newly marked offline."""

    for device_id in mark_offline_devices(db):
        event = anomaly_service.create(
            db,
            event_type="DEVICE_FAILURE",
            severity="MEDIUM",
            source=device_id,
            description="Device heartbeat timed out; the device is offline.",
            details={"status": "OFFLINE"},
        )
        await publish_event(event)


@router.get("/health")
async def health(db: Session = Depends(get_db)) -> dict:
    """Return local edge health and the number of currently online devices."""

    await publish_device_timeouts(db)
    devices = db.scalars(select(Device)).all()
    return {
        "status": "healthy",
        "service": "airport-edge",
        "timestamp": datetime.now(timezone.utc),
        "devices_total": len(devices),
        "devices_online": sum(device.status == "ONLINE" for device in devices),
        "processing": "local",
    }


@router.get("/passenger/{passenger_id}", response_model=PassengerOut)
def get_passenger(passenger_id: str, db: Session = Depends(get_db)) -> Passenger:
    """Return the requested synthetic passenger profile."""

    return require_passenger(db, passenger_id)


@router.post("/identity/verify")
async def identity_verify(payload: IdentityVerifyRequest, db: Session = Depends(get_db)) -> dict:
    """Record identity capture, identity match, and boarding-pass results separately."""

    passenger = require_passenger(db, payload.passenger_id)
    result, event = verify_identity(
        db,
        passenger,
        identity_detected=payload.identity_detected,
        identity_match=payload.mock_identity_match,
        boarding_pass_present=payload.boarding_pass_present,
        flight_number=payload.flight_number,
    )
    if event:
        await publish_event(event)
    return result


@router.post("/checkin/self")
async def self_checkin(payload: SelfCheckinRequest, db: Session = Depends(get_db)) -> dict:
    """Validate passenger answers and complete check-in only when all checks pass."""

    passenger = require_passenger(db, payload.passenger_id)
    result, event = complete_self_checkin(db, passenger, payload.answers)
    if event:
        await publish_event(event)
    return result


@router.post("/checkin/assisted")
async def assisted_checkin(payload: AssistedCheckinRequest, db: Session = Depends(get_db)) -> dict:
    """Check operator identity, flight, boarding pass, and baggage clearance."""

    passenger = require_passenger(db, payload.passenger_id)
    checks = {
        "identity": payload.identity_verified and passenger.identity_verified,
        "boarding_pass": payload.boarding_pass_verified and passenger.boarding_pass_verified,
        "flight": payload.flight_number.strip().casefold() == passenger.flight.casefold(),
        "baggage": payload.baggage_status,
    }
    checks["baggage_clearance"] = payload.baggage_status in {"VERIFIED", "CLEARED"}
    passed = all((
        checks["identity"],
        checks["boarding_pass"],
        checks["flight"],
        checks["baggage_clearance"],
    ))
    passenger.checkin_status = "COMPLETED" if passed else "REQUIRES_MANUAL_REVIEW"
    db.commit()
    if not passed:
        event = anomaly_service.create(
            db,
            event_type="ASSISTED_CHECKIN_REVIEW",
            severity="MEDIUM",
            source=payload.operator_id,
            passenger_id=passenger.passenger_id,
            description="Assisted check-in has a failed or unverified step.",
            details={"checks": checks},
        )
        await publish_event(event)
    return {
        "completed": passed,
        "status": passenger.checkin_status,
        "operator_id": payload.operator_id,
        "checks": checks,
    }


@router.post("/camera/scan")
async def camera_scan(payload: CameraScanRequest, db: Session = Depends(get_db)) -> dict:
    """Analyze one camera frame, apply configured rules, and emit review events."""

    mark_heartbeat(db, require_device(db, payload.device_id), "ONLINE")
    detections = vision_model.detect(
        payload.image,
        [item.model_dump() for item in payload.detections],
    )
    findings = evaluate_detections(db, detections, location=payload.location)
    accepted_rule_types = ["OBJECT", "SECURITY_ZONE", "QUANTITY_LIMIT"]
    configured_types = {
        rule.object_type.casefold()
        for rule in db.scalars(select(SecurityRule).where(
            SecurityRule.enabled.is_(True),
            SecurityRule.rule_type.in_(accepted_rule_types),
        )).all()
    }
    unmatched = [item for item in detections if item["object_type"].casefold() not in configured_types]
    result = {
        "device_id": payload.device_id,
        "location": payload.location,
        "frame_id": payload.frame_id,
        "timestamp": payload.timestamp or datetime.now(timezone.utc),
        "result": "ANALYZED",
        "anomaly_detected": bool(findings or unmatched),
        "detections": detections,
        "findings": findings,
    }
    record_scan(
        db,
        scan_type="CAMERA",
        device_id=payload.device_id,
        passenger_id=payload.passenger_id,
        anomaly_detected=bool(findings or unmatched),
    )
    if findings or unmatched:
        event = anomaly_service.create(
            db,
            event_type="CAMERA_SECURITY_ANOMALY",
            severity="HIGH" if findings else "LOW",
            source=payload.device_id,
            passenger_id=payload.passenger_id,
            description=(
                "Potential restricted/prohibited item detected — manual verification required."
                if findings else "Unknown object detected — manual identification required."
            ),
            confidence=max(item["confidence"] for item in (findings or unmatched)),
            details={"frame_id": payload.frame_id, "findings": findings, "unclassified": unmatched},
        )
        await publish_event(event)
    return result


@router.post("/thermal/scan")
async def thermal_scan(payload: ThermalScanRequest, db: Session = Depends(get_db)) -> dict:
    """Compare one thermal reading with policy thresholds; never make a diagnosis."""

    mark_heartbeat(db, require_device(db, payload.device_id), "ONLINE")
    reading = thermal_analyzer.analyze({
        "temperature_c": payload.temperature_c,
        "unusual_pattern": payload.unusual_pattern,
    })
    threshold = configured_temperature_threshold(db)
    over_threshold = reading["temperature_c"] > threshold
    anomaly = over_threshold or reading["unusual_pattern"]
    reasons = []
    if over_threshold:
        reasons.append("Temperature threshold exceeded")
    if reading["unusual_pattern"]:
        reasons.append("Unusual thermal pattern")
    result = {
        "device_id": payload.device_id,
        "temperature": reading["temperature_c"],
        "threshold": threshold,
        "anomaly_detected": anomaly,
        "reason": "; ".join(reasons) if reasons else None,
        "requires_manual_review": anomaly,
        "medical_diagnosis": False,
    }
    record_scan(
        db,
        scan_type="THERMAL",
        device_id=payload.device_id,
        passenger_id=payload.passenger_id,
        anomaly_detected=anomaly,
    )
    if anomaly:
        event = anomaly_service.create(
            db,
            event_type="THERMAL_THRESHOLD",
            severity="MEDIUM",
            source=payload.device_id,
            passenger_id=payload.passenger_id,
            description=result["reason"],
            details={"temperature_c": reading["temperature_c"], "threshold_c": threshold},
        )
        await publish_event(event)
    return result


@router.post("/baggage/scan")
async def baggage_scan(payload: BaggageScanRequest, db: Session = Depends(get_db)) -> dict:
    """Classify a mock baggage scan and flag unknown or rule-matched objects."""

    device_id = payload.device_id
    mark_heartbeat(db, require_device(db, device_id), "ONLINE")
    detections = [item.model_dump() for item in payload.detections]
    detections.extend({"object_type": item, "confidence": 0.9} for item in payload.simulated_objects)
    detections = vision_model.detect(payload.image, detections)
    findings = evaluate_detections(db, detections, location=payload.location, baggage=True)
    accepted_rule_types = ["OBJECT", "SECURITY_ZONE", "QUANTITY_LIMIT", "BAGGAGE"]
    configured_types = {
        rule.object_type.casefold()
        for rule in db.scalars(select(SecurityRule).where(
            SecurityRule.enabled.is_(True),
            SecurityRule.rule_type.in_(accepted_rule_types),
        )).all()
    }
    unmatched = [item for item in detections if item["object_type"].casefold() not in configured_types]
    if findings:
        classification = "REQUIRES_MANUAL_REVIEW"
    elif detections:
        classification = "UNKNOWN"
    else:
        classification = "NORMAL"
    result = {
        "bag_id": payload.bag_id,
        "passenger_id": payload.passenger_id,
        "scan_type": payload.scan_type,
        "classification": classification,
        "detections": detections,
        "findings": findings,
        "unclassified": unmatched,
        "requires_manual_review": bool(findings or unmatched),
        "message": (
            "Potential restricted/prohibited item detected — manual verification required."
            if findings else (
                "Unknown object detected — manual identification required."
                if unmatched else "No configured rule matched; this is not a legal or safety clearance."
            )
        ),
    }
    record_scan(
        db,
        scan_type="BAGGAGE",
        device_id=device_id,
        passenger_id=payload.passenger_id,
        anomaly_detected=bool(findings or unmatched),
    )
    if findings or unmatched:
        event = anomaly_service.create(
            db,
            event_type="BAGGAGE_SECURITY_ANOMALY",
            severity="HIGH" if findings else "LOW",
            source=device_id,
            passenger_id=payload.passenger_id,
            description=result["message"],
            confidence=max(item["confidence"] for item in (findings or unmatched)),
            details={"bag_id": payload.bag_id, "findings": findings, "unclassified": unmatched},
        )
        await publish_event(event)
    return result


@router.post("/anomaly/analyze")
async def analyze_anomaly(payload: AnomalyAnalyzeRequest, db: Session = Depends(get_db)) -> EventOut:
    """Persist and broadcast a client-submitted generic anomaly event."""

    event = anomaly_service.create(db, **payload.model_dump())
    await publish_event(event)
    return EventOut.model_validate(event)


@router.get("/events", response_model=list[EventOut])
def get_events(
    device: str | None = None,
    passenger: str | None = None,
    event_type: str | None = None,
    severity: str | None = None,
    status: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[AirportEvent]:
    """Return recent events narrowed by optional device, passenger, time, and status filters."""

    query = select(AirportEvent)
    if device:
        query = query.where(AirportEvent.source == device)
    if passenger:
        query = query.where(AirportEvent.passenger_id == passenger)
    if event_type:
        query = query.where(AirportEvent.event_type == event_type)
    if severity:
        query = query.where(AirportEvent.severity == severity.upper())
    if status:
        query = query.where(AirportEvent.status == status.upper())
    if since:
        query = query.where(AirportEvent.timestamp >= since)
    if until:
        query = query.where(AirportEvent.timestamp <= until)
    return list(db.scalars(query.order_by(AirportEvent.timestamp.desc()).limit(limit)).all())


@router.get("/metrics")
def get_metrics(db: Session = Depends(get_db)) -> dict:
    """Aggregate passenger, scan, anomaly, and manual-review dashboard metrics."""

    processed = db.scalar(select(func.count()).select_from(Passenger).where(Passenger.identity_detected.is_(True))) or 0
    identities = db.scalar(select(func.count()).select_from(Passenger).where(Passenger.identity_verified.is_(True))) or 0
    checkins = db.scalar(select(func.count()).select_from(Passenger).where(Passenger.checkin_status == "COMPLETED")) or 0
    failed = db.scalar(select(func.count()).select_from(AirportEvent).where(
        AirportEvent.event_type.in_(["CHECKIN_VALIDATION_FAILED", "IDENTITY_MISMATCH", "BOARDING_PASS_MISMATCH"])
    )) or 0
    scans = db.scalar(select(func.count()).select_from(ScanRecord)) or 0
    events = db.scalars(select(AirportEvent)).all()
    return {
        "passengers_processed": processed,
        "identity_verified": identities,
        "checkins_completed": checkins,
        "failed_validations": failed,
        "total_scans": scans,
        "anomalies_detected": len(events),
        "high_severity_events": sum(event.severity in {"HIGH", "CRITICAL"} for event in events),
        "manual_review": sum(event.status == "REQUIRES_MANUAL_REVIEW" for event in events),
    }


@router.patch("/events/{event_id}")
def update_event(
    event_id: str,
    payload: EventStatusUpdate,
    db: Session = Depends(get_db),
) -> EventOut:
    """Update an event's operator workflow status and increment its revision."""

    event = db.get(AirportEvent, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    event.status = payload.status
    event.revision += 1
    db.commit()
    db.refresh(event)
    return EventOut.model_validate(event)


@router.get("/devices")
async def list_devices(db: Session = Depends(get_db)) -> list[dict]:
    """List registered devices after expiring stale heartbeats."""

    await publish_device_timeouts(db)
    return [
        {
            "device_id": device.device_id,
            "device_type": device.device_type,
            "location": device.location,
            "status": device.status,
            "last_seen": device.last_seen,
            "capabilities": device.capabilities,
        }
        for device in db.scalars(select(Device).order_by(Device.device_id)).all()
    ]


@router.post("/devices")
def add_device(payload: DeviceRegistration, db: Session = Depends(get_db)) -> dict:
    """Register a new device or refresh the details of an existing device."""

    device = register_device(db, payload)
    return {
        "device_id": device.device_id,
        "device_type": device.device_type,
        "location": device.location,
        "status": device.status,
        "last_seen": device.last_seen,
        "capabilities": device.capabilities,
    }


@router.post("/devices/{device_id}/heartbeat")
def device_heartbeat(device_id: str, payload: DeviceHeartbeat, db: Session = Depends(get_db)) -> dict:
    """Refresh liveness and status for a registered device."""

    device = require_device(db, device_id)
    device = mark_heartbeat(db, device, payload.status)
    return {"device_id": device.device_id, "status": device.status, "last_seen": device.last_seen}


@router.get("/rules")
def list_rules(db: Session = Depends(get_db)) -> list[dict]:
    """Return all configured security and passenger-validation rules."""

    return [
        {
            "rule_id": rule.rule_id,
            "category": rule.category,
            "object_type": rule.object_type,
            "enabled": rule.enabled,
            "action": rule.action,
            "min_confidence": rule.min_confidence,
            "description": rule.description,
            "rule_type": rule.rule_type,
            "conditions": rule.conditions or {},
        }
        for rule in db.scalars(select(SecurityRule).order_by(SecurityRule.rule_id)).all()
    ]


@router.put("/rules")
def save_rule(payload: RuleInput, db: Session = Depends(get_db)) -> dict:
    """Create or update one configurable rules-engine rule."""

    rule = upsert_rule(db, payload)
    return {
        "rule_id": rule.rule_id,
        "category": rule.category,
        "object_type": rule.object_type,
        "enabled": rule.enabled,
        "action": rule.action,
        "min_confidence": rule.min_confidence,
        "description": rule.description,
        "rule_type": rule.rule_type,
        "conditions": rule.conditions or {},
    }
