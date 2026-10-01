"""Unit 40 (MEADOWOPS-DOM-028): admin-only control to rebuild the simulated
world around today's date. Starts the rebuild on a background worker and
reports its progress - see app.services.repopulate_job."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.core.auth import require_admin
from app.schemas.admin_simulation import RepopulateRequest, RepopulateStatusRead
from app.services.repopulate_job import RepopulateJob, RepopulateStatus
from app.services.world_repopulate import build_repopulate_work

router = APIRouter(prefix="/api/v1/admin/simulation", tags=["admin-simulation"])


def _read(job_status: RepopulateStatus) -> RepopulateStatusRead:
    return RepopulateStatusRead(
        state=job_status.state.value,
        started_at=job_status.started_at,
        finished_at=job_status.finished_at,
        days_done=job_status.days_done,
        days_total=job_status.days_total,
        message=job_status.message,
    )


@router.post(
    "/repopulate", response_model=RepopulateStatusRead, status_code=status.HTTP_202_ACCEPTED
)
def start_repopulate_route(
    payload: RepopulateRequest,
    request: Request,
    _identity: dict[str, str] = Depends(require_admin),
) -> RepopulateStatusRead:
    job: RepopulateJob = request.app.state.repopulate_job
    work = build_repopulate_work(
        request.app.state.engine,
        request.app.state.settings,
        today=datetime.now(timezone.utc).date(),
        history_days=payload.history_days,
    )
    if not job.start(work):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="A rebuild is already running")
    return _read(job.status())


@router.get("/repopulate/status", response_model=RepopulateStatusRead)
def repopulate_status_route(
    request: Request,
    _identity: dict[str, str] = Depends(require_admin),
) -> RepopulateStatusRead:
    return _read(request.app.state.repopulate_job.status())
