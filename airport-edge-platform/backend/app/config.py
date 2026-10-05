"""Environment-backed settings for database, browser access, and mock thresholds."""

import os


# Keep the local database replaceable with a PostgreSQL URL for edge deployments.
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./airport_edge.db")
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
    if origin.strip()
]
THERMAL_THRESHOLD_C = float(os.getenv("THERMAL_THRESHOLD_C", "37.5"))
AI_CONFIDENCE_THRESHOLD = float(os.getenv("AI_CONFIDENCE_THRESHOLD", "0.7"))
