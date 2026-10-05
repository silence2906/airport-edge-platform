"""Focused tests of replaceable mock adapters and model interfaces."""

import pytest

from app.adapters.mock import MockCameraAdapter
from app.services.models import MockAnomalyDetector, MockThermalAnalyzer, MockVisionModel


def test_mock_device_adapter_connection_lifecycle():
    """Enforce connection lifecycle and command behavior in a mock device."""

    camera = MockCameraAdapter("CAM-UNIT", {"frame_id": "FRAME-UNIT"})
    with pytest.raises(RuntimeError):
        camera.receive_data()

    camera.connect()
    assert camera.receive_data()["frame_id"] == "FRAME-UNIT"
    assert camera.send_command({"action": "capture"})["accepted"] is True
    camera.disconnect()
    with pytest.raises(RuntimeError):
        camera.send_command({"action": "capture"})


def test_mock_model_abstractions_preserve_simulated_inputs():
    """Keep mock model contracts deterministic and free of hidden inference."""

    detections = [{"object_type": "demo_object", "confidence": 0.8}]
    assert MockVisionModel().detect("mock-frame", detections) == detections
    reading = {"temperature_c": 38.2, "unusual_pattern": False}
    assert MockThermalAnalyzer().analyze(reading) == reading
    event = {"event_type": "DEVICE_FAILURE", "severity": "LOW"}
    assert MockAnomalyDetector().analyze(event) == event
