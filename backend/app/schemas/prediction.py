from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PredictionCreate(BaseModel):
    game_id: int = Field(gt=0, le=2147483647)
    predicted_team_id: int = Field(gt=0, le=2147483647)


class PredictionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    game_id: int
    predicted_team_id: int
    probability_at_pick: float
    status: str
    points_awarded: int
    created_at: datetime
    resolved_at: datetime | None
