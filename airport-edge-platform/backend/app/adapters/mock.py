"""In-memory adapters that simulate device connections and payload exchange."""

from typing import Any

from app.adapters.base import DeviceAdapter


class MockAdapter(DeviceAdapter):
    """Basic adapter implementation for deterministic, synthetic device inputs."""

    def __init__(self, device_id: str, data: dict[str, Any]) -> None:
        """Create a disconnected mock device with a fixed payload."""

        self.device_id = device_id
        self.data = data
        self.connected = False

    def connect(self) -> None:
        """Mark the simulated device as connected."""

        self.connected = True

    def receive_data(self) -> dict[str, Any]:
        """Return the configured payload, or raise when the device is disconnected."""

        if not self.connected:
            raise RuntimeError(f"Device {self.device_id} is disconnected")
        return {"device_id": self.device_id, **self.data}

    def send_command(self, command: dict[str, Any]) -> dict[str, Any]:
        """Acknowledge a command when connected; mock devices do not execute it."""

        if not self.connected:
            raise RuntimeError(f"Device {self.device_id} is disconnected")
        return {"device_id": self.device_id, "accepted": True, "command": command}

    def disconnect(self) -> None:
        """Mark the simulated device as disconnected."""

        self.connected = False


class MockCameraAdapter(MockAdapter):
    """Mock adapter type reserved for camera frames and capture commands."""


class MockThermalAdapter(MockAdapter):
    """Mock adapter type reserved for thermal sensor readings."""


class MockBaggageScannerAdapter(MockAdapter):
    """Mock adapter type reserved for baggage scan results."""


class MockCheckinKioskAdapter(MockAdapter):
    """Mock adapter type reserved for self-check-in kiosk messages."""
