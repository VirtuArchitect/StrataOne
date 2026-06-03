from dataclasses import dataclass
from typing import Any

import requests
from requests import Session
from requests.auth import HTTPBasicAuth

from strataone.inventory import InventoryItem, NodeInventory
from strataone.state import NodeSpec


@dataclass(frozen=True)
class RedfishCredentials:
    username: str
    password: str


class RedfishClient:
    def __init__(
        self,
        credentials: RedfishCredentials,
        *,
        timeout: float = 10,
        verify_tls: bool = True,
        session: Session | None = None,
    ) -> None:
        self.credentials = credentials
        self.timeout = timeout
        self.verify_tls = verify_tls
        self.session = session or requests.Session()

    def collect_node_inventory(self, node: NodeSpec) -> NodeInventory:
        try:
            system = self._first_member(node.bmc_ip, "/redfish/v1/Systems")
            managers = self._members(node.bmc_ip, "/redfish/v1/Managers")
            chassis = self._members(node.bmc_ip, "/redfish/v1/Chassis")
            update_service = self._optional_get(node.bmc_ip, "/redfish/v1/UpdateService/FirmwareInventory")

            return NodeInventory(
                serial=node.serial,
                bmc_ip=node.bmc_ip,
                reachable=True,
                manufacturer=system.get("Manufacturer"),
                model=system.get("Model"),
                bios_version=system.get("BiosVersion"),
                power_state=system.get("PowerState"),
                processor_count=self._processor_count(system),
                memory_gib=self._memory_gib(system),
                nics=self._inventory_from_links(node.bmc_ip, system, "EthernetInterfaces"),
                storage=self._storage_inventory(node.bmc_ip, system),
                firmware=self._firmware_inventory(node.bmc_ip, update_service, managers, chassis),
                capabilities=self._capabilities(node.bmc_ip, system, managers, update_service),
            )
        except Exception as exc:
            return NodeInventory(
                serial=node.serial,
                bmc_ip=node.bmc_ip,
                reachable=False,
                error=str(exc),
            )

    def mount_virtual_media(self, node: NodeSpec, iso_url: str, *, boot_once: bool = True) -> dict[str, Any]:
        system = self._first_member(node.bmc_ip, "/redfish/v1/Systems")
        manager = self._first_manager_with_virtual_media(node.bmc_ip)
        virtual_media = self._select_virtual_media(node.bmc_ip, manager)
        insert_action = (
            virtual_media.get("Actions", {})
            .get("#VirtualMedia.InsertMedia", {})
            .get("target")
            or f"{virtual_media.get('@odata.id')}/Actions/VirtualMedia.InsertMedia"
        )
        insert_result = self._post(
            node.bmc_ip,
            insert_action,
            {"Image": iso_url, "Inserted": True, "WriteProtected": True},
        )
        boot_result: dict[str, Any] | None = None
        if boot_once:
            system_path = system.get("@odata.id", "/redfish/v1/Systems/1")
            boot_result = self._patch(
                node.bmc_ip,
                system_path,
                {"Boot": {"BootSourceOverrideTarget": "Cd", "BootSourceOverrideEnabled": "Once"}},
            )
        return {
            "virtual_media": virtual_media.get("@odata.id"),
            "insert_media": insert_result,
            "boot_override": boot_result,
        }

    def eject_virtual_media(self, node: NodeSpec) -> dict[str, Any]:
        manager = self._first_manager_with_virtual_media(node.bmc_ip)
        virtual_media = self._select_virtual_media(node.bmc_ip, manager)
        eject_action = (
            virtual_media.get("Actions", {})
            .get("#VirtualMedia.EjectMedia", {})
            .get("target")
            or f"{virtual_media.get('@odata.id')}/Actions/VirtualMedia.EjectMedia"
        )
        return self._post(node.bmc_ip, eject_action, {})

    def _get(self, bmc_ip: str, path: str) -> dict[str, Any]:
        response = self.session.get(
            f"https://{bmc_ip}{path}",
            auth=HTTPBasicAuth(self.credentials.username, self.credentials.password),
            timeout=self.timeout,
            verify=self.verify_tls,
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError(f"Redfish endpoint {path} did not return a JSON object")
        return payload

    def _post(self, bmc_ip: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = self.session.post(
            f"https://{bmc_ip}{path}",
            auth=HTTPBasicAuth(self.credentials.username, self.credentials.password),
            timeout=self.timeout,
            verify=self.verify_tls,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            json=payload,
        )
        response.raise_for_status()
        return self._json_or_status(response)

    def _patch(self, bmc_ip: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = self.session.patch(
            f"https://{bmc_ip}{path}",
            auth=HTTPBasicAuth(self.credentials.username, self.credentials.password),
            timeout=self.timeout,
            verify=self.verify_tls,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            json=payload,
        )
        response.raise_for_status()
        return self._json_or_status(response)

    def _json_or_status(self, response) -> dict[str, Any]:
        if getattr(response, "content", b""):
            payload = response.json()
            return payload if isinstance(payload, dict) else {"payload": payload}
        return {"status_code": getattr(response, "status_code", 200)}

    def _optional_get(self, bmc_ip: str, path: str) -> dict[str, Any] | None:
        try:
            return self._get(bmc_ip, path)
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                return None
            raise

    def _members(self, bmc_ip: str, path: str) -> list[dict[str, Any]]:
        collection = self._get(bmc_ip, path)
        members = collection.get("Members", [])
        results = []
        for member in members:
            member_path = member.get("@odata.id")
            if member_path:
                results.append(self._get(bmc_ip, member_path))
        return results

    def _first_member(self, bmc_ip: str, path: str) -> dict[str, Any]:
        members = self._members(bmc_ip, path)
        if not members:
            raise ValueError(f"Redfish collection {path} returned no members")
        return members[0]

    def _first_manager_with_virtual_media(self, bmc_ip: str) -> dict[str, Any]:
        for manager in self._members(bmc_ip, "/redfish/v1/Managers"):
            if manager.get("VirtualMedia", {}).get("@odata.id"):
                return manager
        raise ValueError("Redfish manager does not advertise VirtualMedia")

    def _select_virtual_media(self, bmc_ip: str, manager: dict[str, Any]) -> dict[str, Any]:
        virtual_media_path = manager.get("VirtualMedia", {}).get("@odata.id")
        if not virtual_media_path:
            raise ValueError("Redfish manager does not advertise VirtualMedia")
        media_members = self._members(bmc_ip, virtual_media_path)
        if not media_members:
            raise ValueError("Redfish VirtualMedia collection returned no members")
        for media in media_members:
            media_types = [str(item).lower() for item in media.get("MediaTypes", [])]
            if any(item in {"cd", "dvd"} for item in media_types):
                return media
        return media_members[0]

    def _inventory_from_links(self, bmc_ip: str, resource: dict[str, Any], key: str) -> list[InventoryItem]:
        link = resource.get(key, {})
        path = link.get("@odata.id")
        if not path:
            return []

        items = []
        for member in self._members(bmc_ip, path):
            items.append(
                InventoryItem(
                    id=str(member.get("Id") or member.get("@odata.id")),
                    name=member.get("Name"),
                    model=member.get("Model") or member.get("PartNumber"),
                    firmware_version=member.get("FirmwareVersion"),
                    status=self._status(member),
                )
            )
        return items

    def _storage_inventory(self, bmc_ip: str, system: dict[str, Any]) -> list[InventoryItem]:
        storage = []
        storage_link = system.get("Storage", {}).get("@odata.id")
        if not storage_link:
            return storage

        for controller in self._members(bmc_ip, storage_link):
            storage.append(
                InventoryItem(
                    id=str(controller.get("Id") or controller.get("@odata.id")),
                    name=controller.get("Name"),
                    model=controller.get("Model"),
                    firmware_version=controller.get("FirmwareVersion"),
                    status=self._status(controller),
                )
            )
            drives = controller.get("Drives", [])
            for drive in drives:
                drive_path = drive.get("@odata.id")
                if not drive_path:
                    continue
                drive_payload = self._get(bmc_ip, drive_path)
                storage.append(
                    InventoryItem(
                        id=str(drive_payload.get("Id") or drive_payload.get("@odata.id")),
                        name=drive_payload.get("Name"),
                        model=drive_payload.get("Model") or drive_payload.get("PartNumber"),
                        firmware_version=drive_payload.get("FirmwareVersion"),
                        status=self._status(drive_payload),
                    )
                )
        return storage

    def _firmware_inventory(
        self,
        bmc_ip: str,
        update_service: dict[str, Any] | None,
        managers: list[dict[str, Any]],
        chassis: list[dict[str, Any]],
    ) -> list[InventoryItem]:
        if update_service and update_service.get("Members"):
            return [
                InventoryItem(
                    id=str(item.get("Id") or item.get("@odata.id")),
                    name=item.get("Name"),
                    model=item.get("SoftwareId") or item.get("Model"),
                    firmware_version=item.get("Version"),
                    status=self._status(item),
                )
                for item in self._members(bmc_ip, "/redfish/v1/UpdateService/FirmwareInventory")
            ]

        items = []
        for resource in [*managers, *chassis]:
            items.append(
                InventoryItem(
                    id=str(resource.get("Id") or resource.get("@odata.id")),
                    name=resource.get("Name"),
                    model=resource.get("Model"),
                    firmware_version=resource.get("FirmwareVersion"),
                    status=self._status(resource),
                )
            )
        return items

    def _capabilities(
        self,
        bmc_ip: str,
        system: dict[str, Any],
        managers: list[dict[str, Any]],
        update_service: dict[str, Any] | None,
    ) -> list[str]:
        capabilities = ["redfish-api"]
        if system.get("Boot"):
            capabilities.append("boot-override")
        if update_service is not None:
            capabilities.append("firmware-inventory")
        for manager in managers:
            virtual_media = manager.get("VirtualMedia", {}).get("@odata.id")
            if virtual_media:
                capabilities.append("virtual-media")
                break
        return sorted(set(capabilities))

    def _processor_count(self, system: dict[str, Any]) -> int | None:
        count = system.get("ProcessorSummary", {}).get("Count")
        return int(count) if count is not None else None

    def _memory_gib(self, system: dict[str, Any]) -> int | None:
        memory = system.get("MemorySummary", {}).get("TotalSystemMemoryGiB")
        return int(memory) if memory is not None else None

    def _status(self, resource: dict[str, Any]) -> str | None:
        status = resource.get("Status")
        if not isinstance(status, dict):
            return None
        health = status.get("Health")
        state = status.get("State")
        return " / ".join(value for value in (state, health) if value)
