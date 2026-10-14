from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.sport import League, Sport, Team
from app.schemas.sport import LeagueOut, SportOut, StandingsGroupOut, TeamOut

router = APIRouter(tags=["leagues"])


@router.get("/sports", response_model=list[SportOut])
def list_sports(db: Session = Depends(get_db)):
    return db.query(Sport).all()


@router.get("/sports/{sport_key}/leagues", response_model=list[LeagueOut])
def list_leagues(sport_key: str = Path(pattern=r"^[a-z_]{1,30}$"), db: Session = Depends(get_db)):
    sport = db.query(Sport).filter(Sport.key == sport_key).first()
    if not sport:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deporte no encontrado.")
    return (
        db.query(League)
        .filter(League.sport_id == sport.id)
        .order_by(League.is_primary.desc())
        .all()
    )


@router.get("/leagues/{league_key}/teams", response_model=list[TeamOut])
def list_teams(league_key: str = Path(pattern=r"^[a-z0-9_]{1,40}$"), db: Session = Depends(get_db)):
    league = db.query(League).filter(League.key == league_key).first()
    if not league:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Liga no encontrada.")
    return (
        db.query(Team)
        .filter(Team.league_id == league.id, Team.is_placeholder.is_(False))
        .order_by(Team.win_pct.desc())
        .all()
    )


@router.get("/leagues/{league_key}/standings", response_model=list[StandingsGroupOut])
def get_standings(league_key: str = Path(pattern=r"^[a-z0-9_]{1,40}$"), db: Session = Depends(get_db)):
    """
    Tabla de posiciones, agrupada por división (o conferencia si no hay
    división, o toda la liga en un solo grupo si no aplica ninguna) con
    "games_back" (partidos detrás del líder del grupo) en vez de un
    porcentaje plano — así se ve como una tabla de posiciones real.

    Los datos se sirven desde la base de datos local, que se mantiene
    actualizada por el proceso de sincronización periódica (ver
    app/services/sync_service.py), no llamando a la API externa en cada
    request de usuario.
    """
    league = db.query(League).filter(League.key == league_key).first()
    if not league:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Liga no encontrada.")

    teams = (
        db.query(Team)
        .filter(Team.league_id == league.id, Team.is_placeholder.is_(False))
        .order_by(Team.win_pct.desc())
        .all()
    )

    standings_groups: dict[str, list[Team]] = {}
    for team_row in teams:
        group_label = team_row.division or team_row.conference or league.name
        standings_groups.setdefault(group_label, []).append(team_row)

    result = []
    for group_name, grouped_teams in standings_groups.items():
        group_leader_wins = grouped_teams[0].wins
        group_leader_losses = grouped_teams[0].losses
        group_entries = []
        for team_row in grouped_teams:
            games_behind = ((group_leader_wins - team_row.wins) + (team_row.losses - group_leader_losses)) / 2
            team_payload = TeamOut.model_validate(team_row).model_dump()
            team_payload["games_back"] = round(max(games_behind, 0.0), 1)
            group_entries.append(team_payload)
        result.append({"group_name": group_name, "teams": group_entries})

    return result
