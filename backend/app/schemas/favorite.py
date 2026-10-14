from pydantic import BaseModel, ConfigDict, Field, field_validator


class FavoriteCreate(BaseModel):
    favorite_type: str  # team | player | league
    target_id: int = Field(gt=0, le=2147483647)

    @field_validator("favorite_type")
    @classmethod
    def validate_type(cls, favorite_type: str) -> str:
        if favorite_type not in ("team", "player", "league"):
            raise ValueError("favorite_type debe ser 'team', 'player' o 'league'.")
        return favorite_type


class FavoriteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    favorite_type: str
    team_id: int | None
    player_id: int | None
    league_id: int | None
