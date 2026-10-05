"""Device registration, heartbeat handling, demo seeding, and timeout checks."""

from datetime import timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Device, utc_now
from app.schemas import DeviceRegistration

DEMO_DEVICES = [
    ("CAM-001", "CAMERA", "CHECKIN-A", ["FRAME_SCAN"]),
    ("CAM-002", "CAMERA", "SECURITY-ENTRY", ["FRAME_SCAN"]),
    ("THERMAL-001", "THERMAL", "CHECKIN-A", ["TEMPERATURE_SCAN"]),
    ("BAGGAGE-001", "BAGGAGE_SCANNER", "BAGGAGE-DROP", ["XRAY_SCAN"]),
    ("KIOSK-001", "CHECKIN_KIOSK", "CHECKIN-A", ["SELF_CHECKIN"]),
]


def seed_devices(db: Session) -> None:
    """Add default simulated devices when they are not already registered."""

    for device_id, device_type, location, capabilities in DEMO_DEVICES:
        if db.get(Device, device_id) is None:
            db.add(Device(
                device_id=device_id,
                device_type=device_type,
                location=location,
                status="ONLINE",
                last_seen=utc_now(),
                capabilities=capabilities,
            ))
    db.commit()


def register_device(db: Session, payload: DeviceRegistration) -> Device:
    """Create or update a device registry entry and mark it online."""

    device = db.get(Device, payload.device_id)
    if device is None:
        device = Device(device_id=payload.device_id, **payload.model_dump(exclude={"device_id"}))
        db.add(device)
    else:
        for key, value in payload.model_dump(exclude={"device_id"}).items():
            setattr(device, key, value)
        device.status = "ONLINE"
    device.last_seen = utc_now()
    db.commit()
    db.refresh(device)
    return device


def mark_heartbeat(db: Session, device: Device, status: str) -> Device:
    """Refresh a device's status and last-seen time from a heartbeat."""

    device.status = status
    device.last_seen = utc_now()
    db.commit()
    db.refresh(device)
    return device


def mark_offline_devices(db: Session, max_age_seconds: int = 90) -> list[str]:
    """Mark timed-out devices offline and return IDs newly changed to offline."""

    now = utc_now()
    newly_offline = []
    for device in db.scalars(select(Device)).all():
        last_seen = device.last_seen
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=timezone.utc)
        if (now - last_seen).total_seconds() > max_age_seconds:
            if device.status != "OFFLINE":
                newly_offline.append(device.device_id)
            device.status = "OFFLINE"
    db.commit()
    return newly_offline
