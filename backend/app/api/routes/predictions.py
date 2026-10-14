from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Path, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_user, get_db
from app.models.prediction import Prediction
from app.models.sport import Game
from app.models.user import User
from app.schemas.prediction import PredictionCreate, PredictionOut
from app.services.probability_service import points_for_prediction, points_lost_for_prediction

router = APIRouter(prefix="/predictions", tags=["predictions"])


def _summarize_team(team_row) -> dict | None:
    if not team_row:
        return None
    return {"id": team_row.id, "name": team_row.name, "logo_url": team_row.logo_url}


def _serialize_prediction(stored_prediction: Prediction) -> dict:
    """
    Historial de predicciones con datos ya listos para mostrar (nombres y
    logos de equipos, marcador), para que el frontend no tenga que hacer
    una petición aparte por cada partido.
    """
    scheduled_game = stored_prediction.game
    return {
        "id": stored_prediction.id,
        "status": stored_prediction.status,  # pending | correct | incorrect
        "points_awarded": stored_prediction.points_awarded,
        "probability_at_pick": round(stored_prediction.probability_at_pick, 3),
        "seen": stored_prediction.seen,
        "created_at": stored_prediction.created_at,
        "resolved_at": stored_prediction.resolved_at,
        "predicted_team": _summarize_team(stored_prediction.predicted_team),
        "game": {
            "id": scheduled_game.id,
            "start_time": scheduled_game.start_time,
            "status": scheduled_game.status,
            "home_score": scheduled_game.home_score,
            "away_score": scheduled_game.away_score,
            "home_team": _summarize_team(scheduled_game.home_team),
            "away_team": _summarize_team(scheduled_game.away_team),
        }
        if scheduled_game
        else None,
    }


@router.get("/me")
def list_my_predictions(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Historial de predicciones del usuario, más recientes primero (máx. 100)."""
    stored_predictions = (
        db.query(Prediction)
        .options(
            joinedload(Prediction.game).joinedload(Game.home_team),
            joinedload(Prediction.game).joinedload(Game.away_team),
            joinedload(Prediction.predicted_team),
        )
        .filter(Prediction.user_id == current_user.id)
        .order_by(Prediction.created_at.desc())
        .limit(100)
        .all()
    )
    return [_serialize_prediction(stored_prediction) for stored_prediction in stored_predictions]


class MarkSeenPayload(BaseModel):
    prediction_ids: list[int] = Field(max_length=200)


@router.post("/me/mark-seen")
def mark_predictions_seen(
    payload: MarkSeenPayload,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Marca como vistas ciertas predicciones (llamar después de mostrarle al
    usuario el aviso de "ganaste/perdiste"), para que no se le vuelva a
    avisar de lo mismo en su próxima visita.
    """
    if not payload.prediction_ids:
        return {"ok": True}
    db.query(Prediction).filter(
        Prediction.id.in_(payload.prediction_ids),
        Prediction.user_id == current_user.id,  # nunca marcar predicciones de otro usuario
    ).update({"seen": True}, synchronize_session=False)
    db.commit()
    return {"ok": True}


@router.delete("/{prediction_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_prediction(
    prediction_id: int = Path(gt=0, le=2147483647),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Borra una predicción del historial del propio usuario. Se permite tanto
    mientras está pendiente como después de resolverse. Si ya tuvo resultado,
    los puntos otorgados o restados no se revierten.
    """
    prediction = (
        db.query(Prediction)
        .filter(Prediction.id == prediction_id, Prediction.user_id == current_user.id)
        .first()
    )
    if not prediction:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Predicción no encontrada.")
    db.delete(prediction)
    db.commit()
    return None


@router.post("", response_model=PredictionOut, status_code=status.HTTP_201_CREATED)
def create_prediction(
    payload: PredictionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Registra la predicción de un usuario sobre el ganador de un partido.

    Reglas:
    - Solo se puede predecir un partido que aún no ha comenzado (status = scheduled).
    - Solo una predicción por usuario y partido.
    - No se descuentan puntos al predecir; solo se otorgan puntos si acierta,
      una vez el partido finaliza (ver services/sync_service.resolve_predictions).
    """
    game = db.get(Game, payload.game_id)
    if not game:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Partido no encontrado.")

    if game.status != "scheduled":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Solo se puede predecir un partido que aún no ha comenzado.",
        )

    # Normaliza a aware: algún driver/DB puede devolver naive y la
    # comparación ingenua contra now(utc) rompería con TypeError (500).
    scheduled_start = game.start_time
    if scheduled_start.tzinfo is None:
        scheduled_start = scheduled_start.replace(tzinfo=timezone.utc)
    if scheduled_start <= datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El partido ya va a comenzar.")

    if payload.predicted_team_id not in (game.home_team_id, game.away_team_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El equipo elegido no participa en este partido.",
        )

    if game.home_win_probability is None:
        chosen_team_probability = 0.5
    elif payload.predicted_team_id == game.home_team_id:
        chosen_team_probability = game.home_win_probability
    else:
        chosen_team_probability = 1 - game.home_win_probability

    prediction = Prediction(
        user_id=current_user.id,
        game_id=game.id,
        predicted_team_id=payload.predicted_team_id,
        probability_at_pick=chosen_team_probability,
    )
    db.add(prediction)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ya predijiste este partido.")
    db.refresh(prediction)
    return prediction


@router.get("/potential-points/{game_id}/{team_id}")
def preview_potential_points(
    game_id: int = Path(gt=0, le=2147483647),
    team_id: int = Path(gt=0, le=2147483647),
    db: Session = Depends(get_db),
):
    """Permite mostrar en el frontend cuántos puntos se ganarían ANTES de confirmar la predicción."""
    target_game = db.get(Game, game_id)
    if not target_game:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Partido no encontrado.")
    if team_id not in (target_game.home_team_id, target_game.away_team_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Equipo no participa en este partido.")

    home_probability = target_game.home_win_probability if target_game.home_win_probability is not None else 0.5
    selected_team_probability = home_probability if team_id == target_game.home_team_id else 1 - home_probability
    return {
        "probability": round(selected_team_probability, 3),
        "potential_points": points_for_prediction(selected_team_probability),
        "potential_loss": points_lost_for_prediction(selected_team_probability),
    }
