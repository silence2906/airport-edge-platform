"""Persistent SQLAlchemy records used by passenger, device, scan, and event flows."""

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def utc_now() -> datetime:
    """Return the current UTC time for consistently timestamped records."""

    return datetime.now(timezone.utc)


class Passenger(Base):
    """Synthetic passenger profile and independent identity/check-in states."""

    __tablename__ = "passengers"

    passenger_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    flight: Mapped[str] = mapped_column(String(20), nullable=False)
    destination: Mapped[str] = mapped_column(String(10), nullable=False)
    identity_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    identity_detected: Mapped[bool] = mapped_column(Boolean, default=False)
    boarding_pass_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    checkin_status: Mapped[str] = mapped_column(String(20), default="PENDING")


class Device(Base):
    """Registry entry describing a connected airport device and its liveness."""

    __tablename__ = "devices"

    device_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    device_type: Mapped[str] = mapped_column(String(40), nullable=False)
    location: Mapped[str] = mapped_column(String(100), default="UNASSIGNED")
    status: Mapped[str] = mapped_column(String(20), default="ONLINE")
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    capabilities: Mapped[list[str]] = mapped_column(JSON, default=list)


class SecurityRule(Base):
    """Configurable policy rule evaluated against model output or workflow data."""

    __tablename__ = "security_rules"

    rule_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    object_type: Mapped[str] = mapped_column(String(100), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    action: Mapped[str] = mapped_column(String(80), default="ALERT_AND_MANUAL_REVIEW")
    min_confidence: Mapped[float] = mapped_column(Float, default=0.7)
    description: Mapped[str] = mapped_column(Text, default="")
    rule_type: Mapped[str] = mapped_column(String(40), default="OBJECT")
    conditions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ScanRecord(Base):
    """Audit record for each camera, thermal, or baggage scan request."""

    __tablename__ = "scans"

    scan_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    scan_type: Mapped[str] = mapped_column(String(30), nullable=False)
    device_id: Mapped[str] = mapped_column(String(64), nullable=False)
    passenger_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    anomaly_detected: Mapped[bool] = mapped_column(Boolean, default=False)


class AirportEvent(Base):
    """Persisted anomaly or operational event exposed to operators and clients."""

    __tablename__ = "events"

    event_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(60), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    passenger_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="REQUIRES_MANUAL_REVIEW")
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    revision: Mapped[int] = mapped_column(Integer, default=1)
