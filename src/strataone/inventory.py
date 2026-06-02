from pydantic import BaseModel, Field


class InventoryItem(BaseModel):
    id: str
    name: str | None = None
    model: str | None = None
    firmware_version: str | None = None
    status: str | None = None


class NodeInventory(BaseModel):
    serial: str
    bmc_ip: str
    reachable: bool
    manufacturer: str | None = None
    model: str | None = None
    bios_version: str | None = None
    power_state: str | None = None
    processor_count: int | None = None
    memory_gib: int | None = None
    nics: list[InventoryItem] = Field(default_factory=list)
    storage: list[InventoryItem] = Field(default_factory=list)
    firmware: list[InventoryItem] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    error: str | None = None


class InventoryReport(BaseModel):
    site_name: str
    provider: str
    nodes: list[NodeInventory]

    @property
    def reachable_count(self) -> int:
        return sum(1 for node in self.nodes if node.reachable)
