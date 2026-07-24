from __future__ import annotations

import asyncio
import json
from fastapi import APIRouter, File, Query, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from sandbox.api.models import (
    CommandRequest,
    CreateRunRequest,
    DraftInterventionPlanRequest,
    ExportRequest,
    ForkRequest,
    InterpretAgentConfigurationRequest,
    InterpretInterventionPlanRequest,
    InterventionPlanCommandRequest,
)
from sandbox.contracts.scenario import ScenarioDraft
from sandbox.core.ids import new_id


router = APIRouter(prefix="/api/v1")


def manager(request: Request):
    return request.app.state.manager


@router.get("/status")
def status(request: Request) -> dict[str, object]:
    return {"service": "parallel-market-sandbox", "runtime_version": request.app.state.settings.runtime_version, "mode": "local"}


@router.get("/runs")
def list_runs(request: Request) -> list[dict[str, object]]:
    return manager(request).list_runs()


@router.get("/providers")
def providers(request: Request) -> list[dict[str, object]]:
    return manager(request).provider_profiles()


@router.post("/providers/{provider_name}/preflight")
async def provider_preflight(provider_name: str, request: Request) -> dict[str, object]:
    return await manager(request).provider_preflight(provider_name)


@router.get("/agent-archetypes")
def agent_archetypes(request: Request) -> dict[str, object]:
    return {"archetypes": manager(request).agent_archetypes()}


@router.post("/agent-configurations/interpret")
async def interpret_agent_configuration(body: InterpretAgentConfigurationRequest, request: Request) -> dict[str, object]:
    return await manager(request).interpret_agent_configuration(
        user_intent=body.user_intent,
        provider_name=body.provider,
    )


@router.post("/scenarios", status_code=201)
def create_scenario(draft: ScenarioDraft, request: Request) -> dict[str, object]:
    return manager(request).create_scenario(draft)


@router.post("/scenarios/{scenario_id}/resolve")
async def resolve_scenario(scenario_id: str, request: Request) -> dict[str, object]:
    resolved = await manager(request).resolve_scenario(scenario_id)
    return resolved.model_dump(mode="json")


@router.post("/runs", status_code=201)
def create_run(body: CreateRunRequest, request: Request) -> dict[str, object]:
    return manager(request).create_run(body.scenario_id, body.resolution_hash)


@router.get("/runs/{run_id}")
def get_run(run_id: str, request: Request) -> dict[str, object]:
    return manager(request).get_run(run_id)


@router.post("/branches/{branch_id}/commands")
def branch_command(branch_id: str, body: CommandRequest, request: Request) -> dict[str, object]:
    return manager(request).command(branch_id, body.client_command_id, body.command_type, body.payload)


@router.get("/branches/{branch_id}/state")
def branch_state(branch_id: str, request: Request, cursor: int | None = Query(default=None, ge=0)) -> dict[str, object]:
    return manager(request).branch_projection(branch_id, cursor)


@router.get("/branches/{branch_id}/events")
def branch_events(branch_id: str, request: Request, after: int = Query(default=0, ge=0), limit: int = Query(default=200, ge=1, le=1_000)) -> dict[str, object]:
    events = manager(request).events.list_events(branch_id, after=after, limit=limit)
    return {"branch_id": branch_id, "after": after, "events": [event.model_dump(mode="json") for event in events], "next_cursor": events[-1].branch_seq if events else after}


@router.get("/branches/{branch_id}/agents/{agent_id}/observations")
def agent_observations(branch_id: str, agent_id: str, request: Request, cursor: int | None = Query(default=None, ge=0), limit: int = Query(default=200, ge=1, le=1_000)) -> dict[str, object]:
    return {"branch_id": branch_id, "agent_id": agent_id, "observations": manager(request).observations(branch_id, agent_id, cursor=cursor, limit=limit)}


@router.get("/branches/{branch_id}/agents")
def branch_agents(branch_id: str, request: Request, cursor: int | None = Query(default=None, ge=0)) -> dict[str, object]:
    return {"branch_id": branch_id, "agents": manager(request).agents(branch_id, cursor=cursor)}


@router.get("/branches/{branch_id}/agents/{agent_id}")
def agent_detail(branch_id: str, agent_id: str, request: Request, cursor: int | None = Query(default=None, ge=0)) -> dict[str, object]:
    return manager(request).agent_detail(branch_id, agent_id, cursor=cursor)


@router.get("/branches/{branch_id}/agents/{agent_id}/decisions")
def agent_decisions(branch_id: str, agent_id: str, request: Request, cursor: int | None = Query(default=None, ge=0), limit: int = Query(default=200, ge=1, le=1_000)) -> dict[str, object]:
    return {"branch_id": branch_id, "agent_id": agent_id, "decisions": manager(request).agent_decisions(branch_id, agent_id, cursor=cursor, limit=limit)}


@router.get("/branches/{branch_id}/agents/{agent_id}/plans")
def agent_plans(branch_id: str, agent_id: str, request: Request, cursor: int | None = Query(default=None, ge=0), limit: int = Query(default=200, ge=1, le=1_000)) -> dict[str, object]:
    return {"branch_id": branch_id, "agent_id": agent_id, "plans": manager(request).agent_plans(branch_id, agent_id, cursor=cursor, limit=limit)}


@router.get("/branches/{branch_id}/agents/{agent_id}/receipts")
def agent_receipts(branch_id: str, agent_id: str, request: Request, cursor: int | None = Query(default=None, ge=0), limit: int = Query(default=200, ge=1, le=1_000)) -> dict[str, object]:
    return {"branch_id": branch_id, "agent_id": agent_id, "receipts": manager(request).agent_receipts(branch_id, agent_id, cursor=cursor, limit=limit)}


@router.get("/branches/{branch_id}/intervention-plans")
def intervention_plans(branch_id: str, request: Request) -> dict[str, object]:
    return {"branch_id": branch_id, "plans": manager(request).intervention_plans(branch_id)}


@router.get("/intervention-templates")
def intervention_templates(request: Request) -> dict[str, object]:
    return {"templates": manager(request).intervention_templates()}


@router.get("/branches/{branch_id}/intervention-plans/{plan_id}")
def intervention_plan(branch_id: str, plan_id: str, request: Request) -> dict[str, object]:
    return manager(request).intervention_plan(branch_id, plan_id)


@router.post("/branches/{branch_id}/intervention-plans", status_code=201)
def draft_intervention_plan(branch_id: str, body: DraftInterventionPlanRequest, request: Request) -> dict[str, object]:
    return manager(request).create_intervention_plan(branch_id, body.client_command_id, body.draft)


@router.post("/branches/{branch_id}/intervention-plans/interpret", status_code=201)
async def interpret_intervention_plan(branch_id: str, body: InterpretInterventionPlanRequest, request: Request) -> dict[str, object]:
    return await manager(request).interpret_intervention_plan(
        branch_id,
        body.client_command_id,
        user_intent=body.user_intent,
        requested_effective_time_us=body.requested_effective_time_us,
        provider_name=body.provider,
        access_scope=body.access_scope,
        private_read_refs=body.private_read_refs,
    )


@router.post("/branches/{branch_id}/intervention-plans/{plan_id}/confirm")
def confirm_intervention_plan(branch_id: str, plan_id: str, body: InterventionPlanCommandRequest, request: Request) -> dict[str, object]:
    return manager(request).confirm_intervention_plan(branch_id, plan_id, body.client_command_id)


@router.post("/branches/{branch_id}/intervention-plans/{plan_id}/reject")
def reject_intervention_plan(branch_id: str, plan_id: str, body: InterventionPlanCommandRequest, request: Request) -> dict[str, object]:
    return manager(request).reject_intervention_plan(branch_id, plan_id, body.client_command_id)


@router.post("/branches/{branch_id}/fork", status_code=201)
def fork_branch(branch_id: str, body: ForkRequest, request: Request) -> dict[str, object]:
    return manager(request).fork(branch_id, body.checkpoint_id, body.client_command_id)


@router.get("/branches/{branch_id}/stream")
async def stream_branch(branch_id: str, request: Request, cursor: int = Query(default=0, ge=0)) -> StreamingResponse:
    async def stream():
        last_event_id = request.headers.get("Last-Event-ID", "")
        current = max(cursor, int(last_event_id) if last_event_id.isdigit() else 0)
        heartbeat = 0
        while not await request.is_disconnected():
            events = manager(request).events.list_events(branch_id, after=current, limit=100)
            if events:
                current = events[-1].branch_seq
                payload = {"cursor": current, "events": [event.model_dump(mode="json") for event in events if event.event_type in {"TradeSettled", "InformationPublished", "BranchPaused", "CheckpointCreated", "BranchCreated"}], "projection": manager(request).branch_projection(branch_id)}
                yield f"id: {current}\nevent: projection\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
            else:
                heartbeat += 1
                yield f": heartbeat {heartbeat}\n\n"
            await asyncio.sleep(1)
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/archives/export")
def export_archive(body: ExportRequest, request: Request) -> dict[str, object]:
    output = request.app.state.settings.archive_dir / f"{body.run_id}.sandbox"
    return manager(request).export_archive(body.run_id, output)


@router.get("/archives/{run_id}/download")
def download_archive(run_id: str, request: Request) -> FileResponse:
    path = request.app.state.settings.archive_dir / f"{run_id}.sandbox"
    return FileResponse(path, filename=f"{run_id}.sandbox", media_type="application/zip")


@router.post("/archives/import")
async def import_archive(request: Request, archive: UploadFile = File(...)) -> dict[str, object]:
    staging = request.app.state.settings.data_dir / "staging"
    staging.mkdir(parents=True, exist_ok=True)
    target = staging / f"{new_id('upload')}.sandbox"
    total = 0
    with target.open("wb") as output:
        while chunk := await archive.read(1024 * 1024):
            total += len(chunk)
            if total > 250 * 1024 * 1024:
                target.unlink(missing_ok=True)
                from sandbox.core.errors import ValidationError
                raise ValidationError("archive exceeds the upload size limit")
            output.write(chunk)
    try:
        return manager(request).import_archive(target)
    finally:
        target.unlink(missing_ok=True)
