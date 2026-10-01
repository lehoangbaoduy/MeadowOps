"""Unit 40: request/response shapes for the admin repopulate routes."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.services.world_repopulate import DEFAULT_HISTORY_DAYS

# The word the Builder must type before the destructive rebuild runs. Checked
# here on the server so the guard does not depend on the UI.
CONFIRM_PHRASE = "REPOPULATE"

MIN_HISTORY_DAYS = 14
MAX_HISTORY_DAYS = 90


class RepopulateRequest(BaseModel):
    confirm: Literal["REPOPULATE"]
    history_days: int = Field(default=DEFAULT_HISTORY_DAYS, ge=MIN_HISTORY_DAYS, le=MAX_HISTORY_DAYS)


class RepopulateStatusRead(BaseModel):
    state: Literal["idle", "running", "succeeded", "failed"]
    started_at: datetime | None
    finished_at: datetime | None
    days_done: int
    days_total: int
    message: str | None
