"""
Panel de administración mínimo: solo sirve para ver y borrar manualmente
equipos incorrectos de la base de datos (ej. si la limpieza automática de
sync_service.py no alcanzó a cubrir algún caso). No incluye ninguna otra
función a propósito, para mantener la superficie de riesgo lo más chica
posible.

Protegido por get_current_admin_user (ver app/api/deps.py): requiere una
sesión ya iniciada con un usuario incluido en ADMIN_USERNAMES. No hay un
segundo password ni un sistema nuevo — reutiliza el login que ya existe.
"""
from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin_user
from app.core.database import get_db
from app.models.sport import ExcludedTeam, League, Team
from app.models.user import User
from app.services.sync_service import delete_teams_cascade

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/teams")
def list_all_teams(
    league_key: str = Query(pattern=r"^[a-z0-9_]{1,40}$"),
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_admin_user),
):
    """
    Lista TODOS los equipos de la liga, incluyendo los que el resto de la
    app oculta (placeholders, sin conferencia asignada, etc.) — a propósito,
    para poder verlos y decidir si hay que borrar alguno a mano.
    """
    league = db.query(League).filter(League.key == league_key).first()
    if not league:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Liga no encontrada.")

    team_rows = db.query(Team).filter(Team.league_id == league.id).order_by(Team.name).all()
    return [
        {
            "id": team_row.id,
            "external_id": team_row.external_id,
            "name": team_row.name,
            "conference": team_row.conference,
            "division": team_row.division,
            "is_placeholder": team_row.is_placeholder,
            "wins": team_row.wins,
            "losses": team_row.losses,
        }
        for team_row in team_rows
    ]


@router.delete("/teams/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_team(
    team_id: int = Path(gt=0, le=2147483647),
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_admin_user),
):
    """
    Borra un equipo y todo lo que dependa de él (partidos, jugadores,
    favoritos), y lo agrega a la lista de exclusión permanente
    (ExcludedTeam) para que ninguna sincronización futura lo vuelva a
    crear, sin importar qué diga la API externa sobre él.
    """
    team = db.get(Team, team_id)
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Equipo no encontrado.")

    already_excluded = (
        db.query(ExcludedTeam)
        .filter(ExcludedTeam.league_id == team.league_id, ExcludedTeam.external_id == team.external_id)
        .first()
    )
    if not already_excluded:
        db.add(ExcludedTeam(league_id=team.league_id, external_id=team.external_id, team_name=team.name))

    delete_teams_cascade(db, [team_id])
    db.commit()
    return None


@router.get("/excluded-teams")
def list_excluded_teams(
    league_key: str = Query(pattern=r"^[a-z0-9_]{1,40}$"),
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_admin_user),
):
    """
    Equipos borrados a mano (ver ExcludedTeam) para esta liga — permite
    deshacer un borrado por error (ej. si se borró un equipo real sin
    querer, como pasó con Denver Nuggets).
    """
    league = db.query(League).filter(League.key == league_key).first()
    if not league:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Liga no encontrada.")

    excluded_rows = (
        db.query(ExcludedTeam)
        .filter(ExcludedTeam.league_id == league.id)
        .order_by(ExcludedTeam.excluded_at.desc())
        .all()
    )
    return [
        {"id": exclusion_row.id, "external_id": exclusion_row.external_id, "team_name": exclusion_row.team_name, "excluded_at": exclusion_row.excluded_at}
        for exclusion_row in excluded_rows
    ]


@router.delete("/excluded-teams/{excluded_team_id}", status_code=status.HTTP_204_NO_CONTENT)
def restore_excluded_team(
    excluded_team_id: int = Path(gt=0, le=2147483647),
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_admin_user),
):
    """
    Deshace un borrado: quita al equipo de la lista de exclusión. El
    equipo en sí NO se recrea aquí — lo hace la sincronización normal en
    su próximo ciclo (máx. 5 minutos), ya que dejará de estar excluido.
    """
    excluded = db.get(ExcludedTeam, excluded_team_id)
    if not excluded:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No estaba en la lista de exclusión.")
    db.delete(excluded)
    db.commit()
    return None


@router.get("/leagues")
def list_all_leagues(
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_admin_user),
):
    """
    Todas las ligas del sitio (de cualquier deporte), con cuántos equipos
    tiene guardados cada una y si su sincronización está activa — para
    poder borrar una liga completa (ej. un evento ya pasado) y volverla a
    activar más adelante si hace falta.
    """
    stored_leagues = db.query(League).order_by(League.name).all()
    return [
        {
            "key": league_row.key,
            "name": league_row.name,
            "sync_enabled": league_row.sync_enabled,
            "team_count": db.query(Team).filter(Team.league_id == league_row.id).count(),
        }
        for league_row in stored_leagues
    ]


@router.delete("/leagues/{league_key}", status_code=status.HTTP_204_NO_CONTENT)
def delete_league(
    league_key: str = Path(pattern=r"^[a-z0-9_]{1,40}$"),
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_admin_user),
):
    """
    Borra TODOS los equipos de la liga (con sus partidos, jugadores y
    favoritos, en cascada) y desactiva su sincronización periódica — para
    que se quede borrada de verdad (ej. un evento ya pasado, como un
    Mundial anterior) y no vuelva a aparecer en el siguiente ciclo de 5
    minutos. Se puede reactivar con POST /admin/leagues/{league_key}/enable
    cuando haga falta de nuevo (ej. el próximo Mundial).
    """
    league = db.query(League).filter(League.key == league_key).first()
    if not league:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Liga no encontrada.")

    team_ids = [team_row.id for team_row in db.query(Team).filter(Team.league_id == league.id).all()]
    delete_teams_cascade(db, team_ids)
    league.sync_enabled = False
    db.commit()
    return None


@router.post("/leagues/{league_key}/enable", status_code=status.HTTP_204_NO_CONTENT)
def enable_league(
    league_key: str = Path(pattern=r"^[a-z0-9_]{1,40}$"),
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_admin_user),
):
    """
    Reactiva la sincronización de una liga que se había borrado. No trae
    los datos de vuelta aquí mismo — eso lo hace el siguiente ciclo de
    sincronización normal (máx. 5 minutos), ya que la liga vuelve a estar
    habilitada.
    """
    league = db.query(League).filter(League.key == league_key).first()
    if not league:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Liga no encontrada.")
    league.sync_enabled = True
    db.commit()
    return None
