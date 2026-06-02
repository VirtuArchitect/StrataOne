from strataone.redfish import RedfishClient, RedfishCredentials
from strataone.state import NodeSpec


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload


class FakeSession:
    def __init__(self, payloads: dict[str, dict]) -> None:
        self.payloads = payloads

    def get(self, url: str, **kwargs) -> FakeResponse:
        path = "/" + url.split("/", 3)[3]
        return FakeResponse(self.payloads[path])


def test_collect_node_inventory_from_standard_redfish_endpoints() -> None:
    session = FakeSession(
        {
            "/redfish/v1/Systems": {"Members": [{"@odata.id": "/redfish/v1/Systems/1"}]},
            "/redfish/v1/Systems/1": {
                "Id": "1",
                "Manufacturer": "Contoso",
                "Model": "EdgeBox 2U",
                "BiosVersion": "1.2.3",
                "PowerState": "On",
                "Boot": {"BootSourceOverrideEnabled": "Disabled"},
                "ProcessorSummary": {"Count": 2},
                "MemorySummary": {"TotalSystemMemoryGiB": 512},
                "EthernetInterfaces": {"@odata.id": "/redfish/v1/Systems/1/EthernetInterfaces"},
                "Storage": {"@odata.id": "/redfish/v1/Systems/1/Storage"},
            },
            "/redfish/v1/Systems/1/EthernetInterfaces": {
                "Members": [{"@odata.id": "/redfish/v1/Systems/1/EthernetInterfaces/NIC1"}]
            },
            "/redfish/v1/Systems/1/EthernetInterfaces/NIC1": {
                "Id": "NIC1",
                "Name": "LOM Port 1",
                "Model": "25GbE",
                "FirmwareVersion": "4.5.6",
                "Status": {"State": "Enabled", "Health": "OK"},
            },
            "/redfish/v1/Systems/1/Storage": {"Members": [{"@odata.id": "/redfish/v1/Systems/1/Storage/RAID"}]},
            "/redfish/v1/Systems/1/Storage/RAID": {
                "Id": "RAID",
                "Name": "RAID Controller",
                "Model": "TriMode",
                "FirmwareVersion": "7.8.9",
                "Status": {"State": "Enabled", "Health": "OK"},
                "Drives": [{"@odata.id": "/redfish/v1/Systems/1/Storage/RAID/Drives/0"}],
            },
            "/redfish/v1/Systems/1/Storage/RAID/Drives/0": {
                "Id": "Drive0",
                "Name": "NVMe 0",
                "Model": "1.92TB",
                "FirmwareVersion": "A1",
                "Status": {"State": "Enabled", "Health": "OK"},
            },
            "/redfish/v1/Managers": {"Members": [{"@odata.id": "/redfish/v1/Managers/1"}]},
            "/redfish/v1/Managers/1": {
                "Id": "BMC",
                "Name": "BMC",
                "Model": "Redfish BMC",
                "FirmwareVersion": "3.2.1",
                "VirtualMedia": {"@odata.id": "/redfish/v1/Managers/1/VirtualMedia"},
            },
            "/redfish/v1/Chassis": {"Members": [{"@odata.id": "/redfish/v1/Chassis/1"}]},
            "/redfish/v1/Chassis/1": {"Id": "Chassis", "Name": "Main Chassis"},
            "/redfish/v1/UpdateService/FirmwareInventory": {
                "Members": [{"@odata.id": "/redfish/v1/UpdateService/FirmwareInventory/BMC"}]
            },
            "/redfish/v1/UpdateService/FirmwareInventory/BMC": {
                "Id": "BMCFirmware",
                "Name": "BMC Firmware",
                "Version": "3.2.1",
                "Status": {"State": "Enabled", "Health": "OK"},
            },
        }
    )
    client = RedfishClient(
        RedfishCredentials(username="admin", password="secret"),
        session=session,
    )

    inventory = client.collect_node_inventory(NodeSpec(serial="ABC123", bmc_ip="10.10.1.11"))

    assert inventory.reachable is True
    assert inventory.manufacturer == "Contoso"
    assert inventory.model == "EdgeBox 2U"
    assert inventory.bios_version == "1.2.3"
    assert inventory.processor_count == 2
    assert inventory.memory_gib == 512
    assert len(inventory.nics) == 1
    assert len(inventory.storage) == 2
    assert len(inventory.firmware) == 1
    assert "boot-override" in inventory.capabilities
    assert "firmware-inventory" in inventory.capabilities
    assert "virtual-media" in inventory.capabilities
