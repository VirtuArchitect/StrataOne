from concurrent.futures import ThreadPoolExecutor
from typing import Any

from strataone.artifacts import ArtifactGenerator
from strataone.orchestrator import Orchestrator
from strataone.preflight import PreflightRunner
from strataone.store import StrataStore, spec_from_record


class JobRunner:
    def __init__(self, store: StrataStore, max_workers: int = 4) -> None:
        self.store = store
        self.executor = ThreadPoolExecutor(max_workers=max_workers)

    def submit(self, site_name: str, action: str) -> str:
        job = self.store.create_job(site_name, action)
        self.executor.submit(self._run, job.id)
        return job.id

    def _run(self, job_id: str) -> None:
        job = self.store.get_job(job_id)
        if job is None:
            return
        self.store.start_job(job_id)
        try:
            site = self.store.get_site(job.site_name)
            if site is None:
                raise ValueError(f"site {job.site_name} not found")
            spec = spec_from_record(site)
            result = self._execute(job.action, spec)
            self.store.finish_job(job_id, result)
        except Exception as exc:
            self.store.fail_job(job_id, str(exc))

    def _execute(self, action: str, spec) -> dict[str, Any]:
        if action == "validate":
            return {
                "valid": True,
                "site_name": spec.site.name,
                "platform": spec.platform.type.value,
                "hardware_provider": spec.hardware.vendor,
                "nodes": len(spec.hardware.nodes),
            }
        if action == "plan":
            return Orchestrator().plan(spec).model_dump(mode="json")
        if action == "preflight":
            return PreflightRunner().run(spec).model_dump(mode="json")
        if action == "artifacts":
            return ArtifactGenerator().generate(spec).model_dump(mode="json")
        raise ValueError(f"unsupported job action {action}")
