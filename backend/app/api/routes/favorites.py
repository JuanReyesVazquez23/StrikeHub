from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.models.favorite import Favorite
from app.models.sport import League, Player, Team
from app.models.user import User
from app.schemas.favorite import FavoriteCreate, FavoriteOut

router = APIRouter(prefix="/favorites", tags=["favorites"])


def _ensure_favorite_target_exists(database: Session, favorite_type: str, target_id: int) -> None:
    model_by_type = {"team": Team, "player": Player, "league": League}
    target_model = model_by_type[favorite_type]
    favorite_target = database.get(target_model, target_id)
    if not favorite_target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{favorite_type} no encontrado.")
    # Los placeholders (ej. "American League" del All-Star) no son equipos
    # reales: no tiene sentido favoritarlos y ensucian el perfil.
    if favorite_type == "team" and getattr(favorite_target, "is_placeholder", False):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ese equipo no se puede marcar como favorito.")


@router.get("/me", response_model=list[FavoriteOut])
def list_my_favorites(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(Favorite).filter(Favorite.user_id == current_user.id).all()


@router.post("", response_model=FavoriteOut, status_code=status.HTTP_201_CREATED)
def add_favorite(
    payload: FavoriteCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _ensure_favorite_target_exists(db, payload.favorite_type, payload.target_id)

    favorite = Favorite(
        user_id=current_user.id,
        favorite_type=payload.favorite_type,
        team_id=payload.target_id if payload.favorite_type == "team" else None,
        player_id=payload.target_id if payload.favorite_type == "player" else None,
        league_id=payload.target_id if payload.favorite_type == "league" else None,
    )
    db.add(favorite)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ya está en tus favoritos.")
    db.refresh(favorite)
    return favorite


@router.delete("/{favorite_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_favorite(
    favorite_id: int = Path(gt=0, le=2147483647),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    favorite = db.get(Favorite, favorite_id)
    if not favorite or favorite.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Favorito no encontrado.")
    db.delete(favorite)
    db.commit()
    return None
