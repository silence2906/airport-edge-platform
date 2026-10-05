"""Seed synthetic passenger profiles and retrieve profiles for workflows."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Passenger


def seed_passengers(db: Session) -> None:
    """Add synthetic demo profiles once, without overwriting existing records."""

    if db.scalar(select(Passenger.passenger_id).limit(1)):
        return
    db.add_all([
        Passenger(
            passenger_id="PAX-10001",
            name="Demo Passenger",
            flight="AI123",
            destination="DEL",
            checkin_status="PENDING",
        ),
        Passenger(
            passenger_id="PAX-10002",
            name="Sample Traveler",
            flight="UK456",
            destination="BOM",
            checkin_status="PENDING",
        ),
    ])
    db.commit()


def find_passenger(db: Session, passenger_id: str) -> Passenger | None:
    """Look up a passenger by ID, returning None when there is no profile."""

    return db.get(Passenger, passenger_id)
