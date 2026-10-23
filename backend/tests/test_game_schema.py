"""
Pruebas del esquema de partidos: la lista debe traer 'details' para que la
tarjeta de un partido finalizado muestre pitcher ganador y perdedor (sin red).
"""
import sys
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.schemas.sport import GameOut  # noqa: E402


def _team(team_id, name):
    return SimpleNamespace(
        id=team_id,
        name=name,
        abbreviation="ABC",
        city="Santo Domingo",
        logo_url=None,
        wins=0,
        losses=0,
        ties=0,
        win_pct=0.5,
        division=None,
        conference=None,
    )


def _game(**overrides):
    base = {
        "id": 1,
        "external_id": "851440",
        "start_time": datetime(2026, 10, 21, 23, 30),
        "status": "final",
        "home_team": _team(1, "Leones del Escogido"),
        "away_team": _team(2, "Gigantes del Cibao"),
        "home_score": 5,
        "away_score": 3,
        "home_win_probability": 0.5,
        "venue": "Estadio Quisqueya",
        "period_status": None,
        "details": {
            "winning_pitcher": "Hansel Robles",
            "losing_pitcher": "Ivan Armstrong",
            "save_pitcher": None,
            "innings_played": 9,
        },
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class GameOutDetailsTest(unittest.TestCase):
    def test_lista_incluye_decisiones_del_partido(self):
        """GameOut (la lista) serializa 'details' igual que el detalle del juego."""
        serialized = GameOut.model_validate(_game()).model_dump()

        self.assertEqual(serialized["details"]["winning_pitcher"], "Hansel Robles")
        self.assertEqual(serialized["details"]["losing_pitcher"], "Ivan Armstrong")
        self.assertIsNone(serialized["details"]["save_pitcher"])

    def test_details_es_opcional(self):
        """Un partido sin detalle (ej. programado y sin pitchers) no rompe el esquema."""
        serialized = GameOut.model_validate(_game(details=None)).model_dump()

        self.assertIsNone(serialized["details"])


if __name__ == "__main__":
    unittest.main()
