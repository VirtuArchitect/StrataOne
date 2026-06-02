from pydantic import BaseModel


class PlanStep(BaseModel):
    phase: str
    action: str
    provider: str


class DeploymentPlan(BaseModel):
    site_name: str
    steps: list[PlanStep]
