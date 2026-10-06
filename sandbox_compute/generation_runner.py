"""Ephemeral finite enumeration entry; no data access, SDK, queue or shared state."""
from datetime import datetime, timezone
import uuid

from decision_core.generation_calculation import calculate_generation, validated_request


def run_generation(request):
    request = validated_request(request)
    return calculate_generation(request,run_id=str(uuid.uuid4()),computed_at_utc=datetime.now(timezone.utc))
