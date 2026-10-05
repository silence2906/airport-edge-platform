"""Hardware-independent contract that concrete device adapters must implement."""

from abc import ABC, abstractmethod
from typing import Any


class DeviceAdapter(ABC):
    """Lifecycle and messaging interface for airport device integrations."""

    @abstractmethod
    def connect(self) -> None:
        """Open or initialize communication with the device."""
        ...

    @abstractmethod
    def receive_data(self) -> dict[str, Any]:
        """Read one normalized device payload for business processing."""
        ...

    @abstractmethod
    def send_command(self, command: dict[str, Any]) -> dict[str, Any]:
        """Send a normalized command and return the device acknowledgement."""
        ...

    @abstractmethod
    def disconnect(self) -> None:
        """Close the device connection and release adapter resources."""
        ...
