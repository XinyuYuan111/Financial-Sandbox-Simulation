from __future__ import annotations

import asyncio
import json
from fastapi import APIRouter, File, Query, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from sandbox.api.models import CommandRequest, CreateRunRequest, ExportRequest, ForkRequest
from sandbox.contracts.action import ActionContract
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


@router.post("/scenarios", status_code=201)
def create_scenario(draft: ScenarioDraft, request: Request) -> dict[str, object]:
    return manager(request).create_scenario(draft)


@router.post("/scenarios/{scenario_id}/resolve")
async def resolve_scenario(scenario_id: str, request: Request) -> dict[str, object]:
    resolved = await manager(request).resolve_scenario(scenario_id)
    return resolved.model_dump(mode="json")


@router.post("/runs", status_code=201)
def create_run(body: CreateRunRequest, request: Request) -> dict[str, object]:
    return manager(request).create_run(body.scenario_id)


@router.get("/runs/{run_id}")
def get_run(run_id: str, request: Request) -> dict[str, object]:
    return manager(request).get_run(run_id)


@router.post("/branches/{branch_id}/actions")
def submit_action(branch_id: str, action: ActionContract, request: Request) -> dict[str, object]:
    if action.branch_id != branch_id:
        from sandbox.core.errors import ValidationError
        raise ValidationError("action branch_id does not match the URL", field_path="branch_id")
    return manager(request).submit_action(action)


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
