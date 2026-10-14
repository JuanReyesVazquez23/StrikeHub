from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    key: str
    name_es: str
    name_en: str


class LeagueOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    key: str
    name: str
    country: str | None
    logo_url: str | None
    is_primary: bool


class TeamOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    abbreviation: str | None
    city: str | None
    logo_url: str | None
    wins: int
    losses: int
    ties: int
    win_pct: float
    division: str | None
    conference: str | None


class StandingsTeamOut(TeamOut):
    """Igual que TeamOut, más 'games_back': partidos detrás del líder de su división/grupo."""

    games_back: float


class StandingsGroupOut(BaseModel):
    """Un grupo de posiciones (ej. una división de MLB, o toda la liga si no aplica división)."""

    group_name: str
    teams: list[StandingsTeamOut]


class PlayerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    position: str | None
    jersey_number: str | None
    photo_url: str | None
    team_id: int


class GameOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    external_id: str
    start_time: datetime
    status: str
    home_team: TeamOut
    away_team: TeamOut
    home_score: int | None
    away_score: int | None
    home_win_probability: float | None
    venue: str | None
    period_status: str | None


class GameDetailOut(GameOut):
    """Incluye el detalle específico del deporte (pitcher ganador, boxscore, goleadores...)."""

    details: dict | None


class NewsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    summary: str | None
    image_url: str | None
    source: str
    article_url: str
    published_at: datetime
    # Detectados al momento de responder (no se guardan en BD): si el
    # titular menciona un equipo conocido, se incluye su nombre y logo.
    team_name: str | None = None
    team_logo_url: str | None = None
