"""Seed and evaluate configurable security rules without making legal decisions."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import AI_CONFIDENCE_THRESHOLD, THERMAL_THRESHOLD_C
from app.models import SecurityRule
from app.schemas import RuleInput


def seed_rules(db: Session) -> None:
    """Insert the synthetic demonstration rule only when no rules exist."""

    if db.scalar(select(SecurityRule.rule_id).limit(1)):
        return
    db.add(SecurityRule(
        rule_id="RULE-DEMO-001",
        category="REQUIRES_MANUAL_REVIEW",
        object_type="mock_demo_restricted",
        enabled=True,
        action="ALERT_AND_MANUAL_REVIEW",
        min_confidence=AI_CONFIDENCE_THRESHOLD,
        description="Synthetic demo rule only; configure airport policy before use.",
        rule_type="OBJECT",
        conditions={},
    ))
    db.commit()


def evaluate_detections(
    db: Session,
    detections: list[dict],
    *,
    location: str | None = None,
    baggage: bool = False,
) -> list[dict]:
    """Match detections against enabled rules and configured thresholds/conditions."""

    accepted_types = {"OBJECT", "SECURITY_ZONE", "QUANTITY_LIMIT"}
    if baggage:
        accepted_types.add("BAGGAGE")
    rules = db.scalars(select(SecurityRule).where(
        SecurityRule.enabled.is_(True),
        SecurityRule.rule_type.in_(accepted_types),
    )).all()
    counts: dict[str, int] = {}
    for detection in detections:
        key = detection["object_type"].casefold()
        counts[key] = counts.get(key, 0) + 1
    findings = []
    for detection in detections:
        for rule in rules:
            if rule.object_type.casefold() != detection["object_type"].casefold():
                continue
            conditions = rule.conditions or {}
            if rule.rule_type == "SECURITY_ZONE":
                zones = conditions.get("zones", [])
                if not isinstance(zones, list) or not location or location not in zones:
                    continue
            if rule.rule_type == "QUANTITY_LIMIT":
                max_quantity = conditions.get("max_quantity")
                if not isinstance(max_quantity, int) or counts[detection["object_type"].casefold()] <= max_quantity:
                    continue
            if detection["confidence"] < max(rule.min_confidence, AI_CONFIDENCE_THRESHOLD):
                continue
            finding = {
                **detection,
                "rule_id": rule.rule_id,
                "category": rule.category,
                "action": rule.action,
                "rule_type": rule.rule_type,
            }
            if rule.rule_type == "QUANTITY_LIMIT":
                finding["quantity"] = counts[detection["object_type"].casefold()]
            findings.append(finding)
    return findings


def configured_temperature_threshold(db: Session) -> float:
    """Return the strictest enabled thermal threshold, or the environment default."""

    rules = db.scalars(select(SecurityRule).where(
        SecurityRule.enabled.is_(True),
        SecurityRule.rule_type == "THERMAL_THRESHOLD",
    )).all()
    thresholds = [
        rule.conditions.get("threshold_c")
        for rule in rules
        if rule.conditions and isinstance(rule.conditions.get("threshold_c"), (int, float))
    ]
    return min(thresholds) if thresholds else THERMAL_THRESHOLD_C


def passenger_validation_rules(db: Session) -> list[SecurityRule]:
    """Return enabled rules that add profile-backed passenger questions."""

    return list(db.scalars(select(SecurityRule).where(
        SecurityRule.enabled.is_(True),
        SecurityRule.rule_type == "PASSENGER_VALIDATION",
    )).all())


def required_passenger_questions(db: Session) -> set[str]:
    """Return normalized required questions, including flight and destination."""

    required = set()
    for rule in passenger_validation_rules(db):
        conditions = rule.conditions or {}
        question = conditions.get("question", rule.object_type)
        profile_field = conditions.get("profile_field")
        if (
            conditions.get("required", True)
            and isinstance(profile_field, str)
            and profile_field in {"flight", "destination", "passenger_id"}
            and isinstance(question, str)
        ):
            required.add(question.strip().casefold())
    required.update({
        "what is your flight number?",
        "what is your destination?",
    })
    return required


def upsert_rule(db: Session, payload: RuleInput) -> SecurityRule:
    """Insert or update a rule from validated API input and return it."""

    rule = db.get(SecurityRule, payload.rule_id)
    if rule is None:
        rule = SecurityRule(rule_id=payload.rule_id, **payload.model_dump(exclude={"rule_id"}))
        db.add(rule)
    else:
        for key, value in payload.model_dump(exclude={"rule_id"}).items():
            setattr(rule, key, value)
    db.commit()
    db.refresh(rule)
    return rule
