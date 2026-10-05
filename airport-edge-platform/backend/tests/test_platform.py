"""Integration tests for API workflows, persistence, and real-time events."""

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import Device, utc_now
from app.services.devices import seed_devices
from app.services.passengers import seed_passengers
from app.services.rules import seed_rules


engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def override_get_db():
    """Provide the isolated in-memory database to each test request."""

    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


def setup_function():
    """Reset and seed an isolated schema before each integration test."""

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestingSessionLocal() as db:
        seed_passengers(db)
        seed_devices(db)
        seed_rules(db)


def test_identity_detection_does_not_imply_verification():
    """Ensure capture alone cannot verify identity or a boarding pass."""

    with TestClient(app) as client:
        response = client.post("/api/v1/identity/verify", json={
            "passenger_id": "PAX-10001",
            "identity_detected": True,
            "mock_identity_match": False,
            "boarding_pass_present": True,
        })
        assert response.status_code == 200
        assert response.json()["identity_detected"] is True
        assert response.json()["identity_verified"] is False
        assert response.json()["boarding_pass_verified"] is False


def test_self_checkin_requires_identity_and_valid_answers():
    """Allow only profile-matching answers after identity and pass verification."""

    with TestClient(app) as client:
        client.post("/api/v1/identity/verify", json={
            "passenger_id": "PAX-10001",
            "mock_identity_match": True,
            "boarding_pass_present": True,
        })
        success = client.post("/api/v1/checkin/self", json={
            "passenger_id": "PAX-10001",
            "answers": [
                {"question": "What is your flight number?", "answer": "AI123"},
                {"question": "What is your destination?", "answer": "DEL"},
            ],
        })
        assert success.json()["completed"] is True
        failed = client.post("/api/v1/checkin/self", json={
            "passenger_id": "PAX-10002",
            "answers": [{"question": "Flight number", "answer": "WRONG"}],
        })
        assert failed.json()["completed"] is False
        assert failed.json()["validations"][0]["validated"] is False


def test_device_scan_rules_thermal_and_event_filters():
    """Exercise camera, thermal, and baggage APIs with seeded mock rules."""

    with TestClient(app) as client:
        camera = client.post("/api/v1/camera/scan", json={
            "device_id": "CAM-001",
            "frame_id": "FRAME-1",
            "detections": [{"object_type": "mock_demo_restricted", "confidence": 0.91}],
        })
        assert camera.status_code == 200
        assert camera.json()["anomaly_detected"] is True
        assert "manual verification required" in client.get("/api/v1/events").json()[0]["description"]

        thermal = client.post("/api/v1/thermal/scan", json={
            "device_id": "THERMAL-001",
            "temperature_c": 38.2,
        })
        assert thermal.json()["anomaly_detected"] is True
        assert thermal.json()["medical_diagnosis"] is False

        baggage = client.post("/api/v1/baggage/scan", json={
            "bag_id": "BAG-1",
            "simulated_objects": ["mock_demo_restricted"],
        })
        assert baggage.json()["classification"] == "REQUIRES_MANUAL_REVIEW"
        assert client.get("/api/v1/events?severity=HIGH").status_code == 200
        assert client.get("/api/v1/metrics").json()["total_scans"] == 3


def test_device_registration_heartbeat_and_missing_passenger():
    """Cover device registration, liveness, and unknown resource errors."""

    with TestClient(app) as client:
        response = client.post("/api/v1/devices", json={
            "device_id": "CAM-NEW",
            "device_type": "CAMERA",
            "location": "GATE-1",
            "capabilities": ["FRAME_SCAN"],
        })
        assert response.status_code == 200
        heartbeat = client.post("/api/v1/devices/CAM-NEW/heartbeat", json={"status": "DEGRADED"})
        assert heartbeat.json()["status"] == "DEGRADED"
        assert client.get("/api/v1/passenger/UNKNOWN").status_code == 404
        assert client.post("/api/v1/camera/scan", json={
            "device_id": "MISSING-CAMERA",
            "frame_id": "FRAME-404",
        }).status_code == 404


def test_device_timeout_marks_offline_and_creates_event():
    """Turn stale device heartbeats into offline states and anomaly events."""

    with TestingSessionLocal() as db:
        device = db.get(Device, "CAM-001")
        device.last_seen = utc_now().replace(year=utc_now().year - 1)
        db.commit()

    with TestClient(app) as client:
        health = client.get("/api/v1/health")
        assert health.json()["devices_online"] < health.json()["devices_total"]
        event = client.get("/api/v1/events?event_type=DEVICE_FAILURE").json()
        assert any(item["source"] == "CAM-001" for item in event)


def test_assisted_checkin_requires_baggage_review_and_verified_profile():
    """Require actual profile checks and baggage clearance for assisted check-in."""

    with TestClient(app) as client:
        client.post("/api/v1/identity/verify", json={
            "passenger_id": "PAX-10001",
            "mock_identity_match": True,
            "boarding_pass_present": True,
        })
        payload = {
            "passenger_id": "PAX-10001",
            "operator_id": "OP-001",
            "identity_verified": True,
            "boarding_pass_verified": True,
            "flight_number": "WRONG",
            "baggage_status": "PENDING",
        }
        pending = client.post("/api/v1/checkin/assisted", json=payload)
        assert pending.json()["completed"] is False
        payload["baggage_status"] = "VERIFIED"
        payload["flight_number"] = "AI123"
        completed = client.post("/api/v1/checkin/assisted", json=payload)
        assert completed.json()["completed"] is True


def test_websocket_receives_events():
    """Broadcast each created event to all connected WebSocket clients."""

    with TestClient(app) as client:
        with client.websocket_connect("/ws/events") as websocket, client.websocket_connect("/ws/events") as second:
            response = client.post("/api/v1/anomaly/analyze", json={
                "event_type": "DEVICE_FAILURE",
                "source": "CAM-001",
                "description": "Mock camera disconnected",
                "severity": "HIGH",
            })
            assert response.status_code == 200
            event = websocket.receive_json()
            second_event = second.receive_json()
            assert event["event_type"] == "DEVICE_FAILURE"
            assert second_event["event_id"] == event["event_id"]


def test_configurable_rules_and_unknown_object_manual_review():
    """Apply configured quantity rules and route unknown objects to review."""

    with TestClient(app) as client:
        configured = client.put("/api/v1/rules", json={
            "rule_id": "RULE-QUANTITY-1",
            "category": "RESTRICTED",
            "object_type": "demo_bottle",
            "rule_type": "QUANTITY_LIMIT",
            "conditions": {"max_quantity": 1},
            "min_confidence": 0.7,
        })
        assert configured.status_code == 200
        assert configured.json()["conditions"]["max_quantity"] == 1
        scan = client.post("/api/v1/baggage/scan", json={
            "bag_id": "BAG-QUANTITY",
            "detections": [
                {"object_type": "demo_bottle", "confidence": 0.9},
                {"object_type": "demo_bottle", "confidence": 0.9},
            ],
        })
        assert scan.json()["classification"] == "REQUIRES_MANUAL_REVIEW"
        assert scan.json()["findings"][0]["quantity"] == 2
        unknown = client.post("/api/v1/baggage/scan", json={
            "bag_id": "BAG-UNKNOWN",
            "simulated_objects": ["unclassified_mock_object"],
        })
        assert unknown.json()["classification"] == "UNKNOWN"
        assert unknown.json()["requires_manual_review"] is True


def test_configurable_temperature_threshold_and_zone_rule():
    """Use policy-configured thermal limits and security-zone matching."""

    with TestClient(app) as client:
        rule = client.put("/api/v1/rules", json={
            "rule_id": "RULE-TEMP-1",
            "category": "THERMAL_ANOMALY",
            "object_type": "temperature_c",
            "rule_type": "THERMAL_THRESHOLD",
            "conditions": {"threshold_c": 36.8},
        })
        assert rule.status_code == 200
        reading = client.post("/api/v1/thermal/scan", json={
            "device_id": "THERMAL-001",
            "temperature_c": 37.0,
        })
        assert reading.json()["threshold"] == 36.8
        assert reading.json()["anomaly_detected"] is True

        zone_rule = client.put("/api/v1/rules", json={
            "rule_id": "RULE-ZONE-1",
            "category": "REQUIRES_MANUAL_REVIEW",
            "object_type": "demo_zone_item",
            "rule_type": "SECURITY_ZONE",
            "conditions": {"zones": ["SECURITY-ENTRY"]},
        })
        assert zone_rule.status_code == 200
        scan = client.post("/api/v1/camera/scan", json={
            "device_id": "CAM-002",
            "location": "SECURITY-ENTRY",
            "frame_id": "FRAME-ZONE",
            "detections": [{"object_type": "demo_zone_item", "confidence": 0.9}],
        })
        assert scan.json()["anomaly_detected"] is True


def test_configurable_passenger_validation_rule():
    """Require extra passenger answers backed by the synthetic profile."""

    with TestClient(app) as client:
        rule = client.put("/api/v1/rules", json={
            "rule_id": "RULE-PASSENGER-ID",
            "category": "PASSENGER_VALIDATION",
            "object_type": "passenger_id",
            "rule_type": "PASSENGER_VALIDATION",
            "conditions": {
                "question": "What is your passenger ID?",
                "profile_field": "passenger_id",
            },
        })
        assert rule.status_code == 200
        client.post("/api/v1/identity/verify", json={
            "passenger_id": "PAX-10001",
            "mock_identity_match": True,
            "boarding_pass_present": True,
        })
        checkin = client.post("/api/v1/checkin/self", json={
            "passenger_id": "PAX-10001",
            "answers": [
                {"question": "What is your flight number?", "answer": "AI123"},
                {"question": "What is your destination?", "answer": "DEL"},
                {"question": "What is your passenger ID?", "answer": "PAX-10001"},
            ],
        })
        assert checkin.json()["completed"] is True
