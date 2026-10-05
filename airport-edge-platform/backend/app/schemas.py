"""Validated request and response shapes shared by the versioned API routes."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class PassengerOut(BaseModel):
    """Passenger profile fields safe to return to the prototype clients."""

    passenger_id: str
    name: str
    identity_detected: bool
    identity_verified: bool
    boarding_pass_verified: bool
    flight: str
    destination: str
    checkin_status: str

    model_config = {"from_attributes": True}


class IdentityVerifyRequest(BaseModel):
    """Mock identity capture and boarding-pass evidence supplied by a client."""

    passenger_id: str
    identity_detected: bool = True
    mock_identity_match: bool = Field(
        description="Mock verifier result; replace with an identity provider adapter."
    )
    boarding_pass_present: bool = True
    flight_number: str | None = None


class AnswerInput(BaseModel):
    """One passenger response to a profile-backed check-in question."""

    question: str
    answer: str


class SelfCheckinRequest(BaseModel):
    """Self-service check-in request with the answers to validate."""

    passenger_id: str
    answers: list[AnswerInput] = Field(default_factory=list)


class AssistedCheckinRequest(BaseModel):
    """Operator-submitted checks required to complete assisted check-in."""

    passenger_id: str
    operator_id: str
    identity_verified: bool
    boarding_pass_verified: bool
    flight_number: str
    baggage_status: str = "PENDING"


class Detection(BaseModel):
    """Candidate object label and model confidence, not a legal classification."""

    object_type: str
    confidence: float = Field(ge=0, le=1)


class CameraScanRequest(BaseModel):
    """Camera frame metadata and optional mock detections sent to the edge API."""

    device_id: str = "CAM-001"
    location: str = "CHECKIN-A"
    timestamp: datetime | None = None
    frame_id: str
    passenger_id: str | None = None
    detections: list[Detection] = Field(default_factory=list)
    image: str | None = None


class ThermalScanRequest(BaseModel):
    """Thermal sensor reading for configurable, non-medical anomaly analysis."""

    device_id: str = "THERMAL-001"
    temperature_c: float
    unusual_pattern: bool = False
    passenger_id: str | None = None


class BaggageScanRequest(BaseModel):
    """Mock baggage image or detections submitted by a scanner client."""

    device_id: str = "BAGGAGE-001"
    location: str = "BAGGAGE-DROP"
    bag_id: str
    passenger_id: str | None = None
    scan_type: str = "XRAY"
    image: str | None = None
    detections: list[Detection] = Field(default_factory=list)
    simulated_objects: list[str] = Field(default_factory=list)


class AnomalyAnalyzeRequest(BaseModel):
    """Generic event data submitted to the anomaly/event service."""

    event_type: str
    source: str
    description: str
    severity: str = "MEDIUM"
    confidence: float | None = Field(default=None, ge=0, le=1)
    passenger_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class DeviceRegistration(BaseModel):
    """Device identity, location, and declared capabilities for registration."""

    device_id: str
    device_type: str
    location: str = "UNASSIGNED"
    capabilities: list[str] = Field(default_factory=list)


class DeviceHeartbeat(BaseModel):
    """Latest supported liveness state reported by a registered device."""

    status: Literal["ONLINE", "DEGRADED"] = "ONLINE"


class RuleInput(BaseModel):
    """Rule-engine configuration, including its type-specific conditions."""

    rule_id: str
    category: str
    object_type: str
    enabled: bool = True
    action: str = "ALERT_AND_MANUAL_REVIEW"
    min_confidence: float = Field(default=0.7, ge=0, le=1)
    description: str = ""
    rule_type: Literal[
        "OBJECT",
        "BAGGAGE",
        "THERMAL_THRESHOLD",
        "SECURITY_ZONE",
        "QUANTITY_LIMIT",
        "PASSENGER_VALIDATION",
    ] = "OBJECT"
    conditions: dict[str, Any] = Field(default_factory=dict)


class EventStatusUpdate(BaseModel):
    """Operator-approved workflow status update for a persisted event."""

    status: Literal["ACKNOWLEDGED", "RESOLVED", "REQUIRES_MANUAL_REVIEW"]


class EventOut(BaseModel):
    """Serialized event fields returned by REST and WebSocket interfaces."""

    event_id: str
    event_type: str
    severity: str
    source: str
    passenger_id: str | None
    timestamp: datetime
    description: str
    confidence: float | None
    status: str
    details: dict[str, Any]

    model_config = {"from_attributes": True}
