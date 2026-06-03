import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel


class OemValidationRecord(BaseModel):
    provider: str
    operation: str
    status: str = "not-validated"
    lab: str | None = None
    validated_at: str | None = None
    evidence: str | None = None
    notes: str | None = None

    @property
    def validated(self) -> bool:
        return self.status == "validated"


def oem_validation_required() -> bool:
    return os.getenv("STRATAONE_REQUIRE_OEM_VALIDATION", "false").lower() in {"1", "true", "yes", "on"}


def validation_registry_path() -> Path:
    return Path(os.getenv("STRATAONE_OEM_VALIDATION_FILE", ".strataone/oem-validation.json"))


def list_oem_validation_records() -> list[OemValidationRecord]:
    path = validation_registry_path()
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = payload.get("records", payload) if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        return []
    return [OemValidationRecord.model_validate(record) for record in records]


def live_operation_allowed(provider: str, operation: str) -> bool:
    if not oem_validation_required():
        return True
    return any(record.provider == provider and record.operation == operation and record.validated for record in list_oem_validation_records())


def validation_summary() -> dict[str, Any]:
    records = list_oem_validation_records()
    return {
        "required": oem_validation_required(),
        "registry": str(validation_registry_path()),
        "validated": [record.model_dump(mode="json") for record in records if record.validated],
        "pending": [record.model_dump(mode="json") for record in records if not record.validated],
    }
