import json

from strataone.validation import live_operation_allowed, validation_summary


def test_oem_validation_gate_blocks_unvalidated_live_operations(tmp_path, monkeypatch) -> None:
    registry = tmp_path / "oem-validation.json"
    registry.write_text(json.dumps({"records": []}), encoding="utf-8")
    monkeypatch.setenv("STRATAONE_REQUIRE_OEM_VALIDATION", "true")
    monkeypatch.setenv("STRATAONE_OEM_VALIDATION_FILE", str(registry))

    assert live_operation_allowed("generic-redfish", "redfish-virtual-media") is False


def test_oem_validation_gate_allows_validated_provider_operation(tmp_path, monkeypatch) -> None:
    registry = tmp_path / "oem-validation.json"
    registry.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "provider": "generic-redfish",
                        "operation": "redfish-virtual-media",
                        "status": "validated",
                        "lab": "edge-lab-1",
                        "evidence": "change-12345",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("STRATAONE_REQUIRE_OEM_VALIDATION", "true")
    monkeypatch.setenv("STRATAONE_OEM_VALIDATION_FILE", str(registry))

    assert live_operation_allowed("generic-redfish", "redfish-virtual-media") is True
    assert validation_summary()["validated"][0]["provider"] == "generic-redfish"
