"""Replaceable interfaces and pass-through mock implementations for edge AI."""

from abc import ABC, abstractmethod
from typing import Any


class VisionModel(ABC):
    """Contract for image/frame object detection plugged into camera workflows."""

    @abstractmethod
    def detect(self, image: str | None, supplied_detections: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Return candidate labels and confidence; this is not a security decision."""


class MockVisionModel(VisionModel):
    """Return supplied detections unchanged until a real model is configured."""

    def detect(self, image: str | None, supplied_detections: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Pass simulated detections through without inferring new labels."""

        return supplied_detections


class ThermalAnalyzer(ABC):
    """Contract for analyzing thermal sensor samples without medical diagnosis."""

    @abstractmethod
    def analyze(self, thermal_data: dict[str, Any]) -> dict[str, Any]:
        """Analyze a sensor reading without making a medical diagnosis."""


class MockThermalAnalyzer(ThermalAnalyzer):
    """Pass through synthetic thermal readings for deterministic testing."""

    def analyze(self, thermal_data: dict[str, Any]) -> dict[str, Any]:
        """Return the supplied thermal sample without modifying it."""

        return thermal_data


class AnomalyDetector(ABC):
    """Contract for normalizing anomaly candidates before persistence."""

    @abstractmethod
    def analyze(self, event: dict[str, Any]) -> dict[str, Any]:
        """Normalize a candidate event for the event service."""


class MockAnomalyDetector(AnomalyDetector):
    """Pass event data through until a deployment-specific detector is supplied."""

    def analyze(self, event: dict[str, Any]) -> dict[str, Any]:
        """Return the candidate event unchanged."""

        return event
