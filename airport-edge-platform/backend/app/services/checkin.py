"""Identity, boarding-pass, and passenger-answer validation workflows."""

from sqlalchemy.orm import Session

from app.models import AirportEvent, Passenger
from app.schemas import AnswerInput
from app.services.anomalies import anomaly_service
from app.services.rules import passenger_validation_rules, required_passenger_questions


def verify_identity(
    db: Session,
    passenger: Passenger,
    *,
    identity_detected: bool,
    identity_match: bool,
    boarding_pass_present: bool,
    flight_number: str | None,
) -> tuple[dict, AirportEvent | None]:
    """Set separate capture, identity, and boarding-pass verification states."""

    passenger.identity_detected = identity_detected
    passenger.identity_verified = bool(identity_detected and identity_match)
    passenger.boarding_pass_verified = bool(
        passenger.identity_verified
        and boarding_pass_present
        and (flight_number is None or flight_number.casefold() == passenger.flight.casefold())
    )
    db.commit()
    result = {
        "passenger_id": passenger.passenger_id,
        "identity_detected": passenger.identity_detected,
        "identity_verified": passenger.identity_verified,
        "boarding_pass_verified": passenger.boarding_pass_verified,
    }
    event = None
    if identity_detected and not passenger.identity_verified:
        event = anomaly_service.create(
            db,
            event_type="IDENTITY_MISMATCH",
            severity="HIGH",
            source="IDENTITY",
            passenger_id=passenger.passenger_id,
            description="Identity capture did not match the mock passenger profile.",
        )
    if passenger.identity_verified and not passenger.boarding_pass_verified:
        event = anomaly_service.create(
            db,
            event_type="BOARDING_PASS_MISMATCH",
            severity="MEDIUM",
            source="IDENTITY",
            passenger_id=passenger.passenger_id,
            description="Boarding pass or flight information did not verify.",
        )
    return result, event


def validate_answers(db: Session, passenger: Passenger, answers: list[AnswerInput]) -> list[dict]:
    """Compare each supplied answer with its expected synthetic profile value."""

    expected = {
        "what is your flight number?": passenger.flight,
        "flight number": passenger.flight,
        "what is your destination?": passenger.destination,
        "destination": passenger.destination,
    }
    profile_fields = {
        "flight": passenger.flight,
        "destination": passenger.destination,
        "passenger_id": passenger.passenger_id,
    }
    for rule in passenger_validation_rules(db):
        conditions = rule.conditions or {}
        profile_field = conditions.get("profile_field")
        question = conditions.get("question", rule.object_type)
        if isinstance(profile_field, str) and profile_field in profile_fields and isinstance(question, str):
            expected[question.strip().casefold()] = profile_fields[profile_field]
    results = []
    for item in answers:
        normalized_question = item.question.strip().casefold()
        expected_value = expected.get(normalized_question)
        validated = expected_value is not None and item.answer.strip().casefold() == expected_value.casefold()
        results.append({
            "question": item.question,
            "answer": item.answer,
            "expected": expected_value,
            "validated": validated,
            "confidence": 1.0 if validated else 0.0,
            "action": "CONTINUE" if validated else "FLAG_FOR_MANUAL_REVIEW",
        })
    return results


def complete_self_checkin(
    db: Session,
    passenger: Passenger,
    answers: list[AnswerInput],
) -> tuple[dict, AirportEvent | None]:
    """Complete self check-in only after identity and required answers validate."""

    validations = validate_answers(db, passenger, answers)
    failed = any(not result["validated"] for result in validations)
    covered_questions = {
        result["question"].strip().casefold()
        for result in validations
        if result["validated"]
    }
    if not required_passenger_questions(db).issubset(covered_questions):
        failed = True
    if not passenger.identity_verified or not passenger.boarding_pass_verified:
        failed = True
    if failed:
        passenger.checkin_status = "REQUIRES_MANUAL_REVIEW"
        db.commit()
        event = anomaly_service.create(
            db,
            event_type="CHECKIN_VALIDATION_FAILED",
            severity="MEDIUM",
            source="SELF_CHECKIN",
            passenger_id=passenger.passenger_id,
            description="Self check-in validation failed; operator review is required.",
            details={"validations": validations},
        )
        return (
            {"completed": False, "status": passenger.checkin_status, "validations": validations},
            event,
        )
    passenger.checkin_status = "COMPLETED"
    db.commit()
    return (
        {"completed": True, "status": passenger.checkin_status, "validations": validations},
        None,
    )
