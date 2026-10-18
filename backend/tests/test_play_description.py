"""
Pruebas de la jugada en español del marcador en vivo (sin red, sin servidor).

Ejecutar desde backend/:
    python -m pytest tests/ -q
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.mlb_service import extract_live_situation  # noqa: E402
from app.services.play_description import describe_play_in_spanish  # noqa: E402


def _play(event_type, batter="Jonathan Guzmán", rbi=0, description="Play.", is_complete=True):
    return {
        "result": {"eventType": event_type, "rbi": rbi, "description": description},
        "about": {"isComplete": is_complete},
        "matchup": {"batter": {"fullName": batter}},
    }


class DescribePlayInSpanishTest(unittest.TestCase):
    def test_sencillo_conserva_el_nombre_con_acentos(self):
        self.assertEqual(
            describe_play_in_spanish(_play("single", description="Jonathan Guzmán singles on a line drive.")),
            "Jonathan Guzmán pega sencillo.",
        )

    def test_doble_que_remolca_una_carrera(self):
        self.assertEqual(
            describe_play_in_spanish(
                _play("double", batter="Erik González", rbi=1, description="Erik González doubles (3). ...")
            ),
            "Erik González pega doble y remolca 1 carrera.",
        )

    def test_jonron_con_varias_remolcadas(self):
        self.assertEqual(
            describe_play_in_spanish(_play("home_run", batter="Sócrates Brito", rbi=3)),
            "Sócrates Brito conecta jonrón y remolca 3 carreras.",
        )

    def test_jugadas_frecuentes(self):
        casos = {
            "strikeout": "Vidal Bruján se poncha.",
            "field_out": "Vidal Bruján batea para out.",
            "walk": "Vidal Bruján recibe base por bolas.",
            "hit_by_pitch": "Vidal Bruján es golpeado por el pitcheo.",
            "field_error": "Vidal Bruján llega a base por error.",
            "grounded_into_double_play": "Vidal Bruján batea para doble play.",
        }
        for event_type, esperado in casos.items():
            with self.subTest(event_type=event_type):
                self.assertEqual(describe_play_in_spanish(_play(event_type, batter="Vidal Bruján")), esperado)

    def test_las_jugadas_de_campo_dicen_como_salio_la_bola(self):
        casos = {
            "flies out to center fielder Victor Scott II.": "elevado",
            "grounds out, shortstop Emil Morales to first baseman Aderlin Rodríguez.": "rodado",
            "lines out to left fielder Chandler Simpson.": "línea",
            "pops out to second baseman Eddinson Paulino.": "elevado corto",
        }
        for description, batted_ball in casos.items():
            with self.subTest(description=description):
                self.assertEqual(
                    describe_play_in_spanish(_play("field_out", batter="Roldy Brito", description=description)),
                    f"Roldy Brito se retira con {batted_ball}.",
                )

    def test_out_por_fuerza_dice_como_salio_la_bola(self):
        self.assertEqual(
            describe_play_in_spanish(
                _play(
                    "force_out",
                    description="Victor Scott II grounds into a force out, second baseman Eddinson Paulino to shortstop Emil Morales.",
                )
            ),
            "Jonathan Guzmán se retira con rodado por fuerza.",
        )

    def test_out_sin_detalle_de_la_bola_usa_la_frase_generica(self):
        self.assertEqual(
            describe_play_in_spanish(_play("field_out", description="Out recorded.")),
            "Jonathan Guzmán batea para out.",
        )

    def test_la_jugada_de_campo_con_remolcada_suma_la_clausula(self):
        self.assertEqual(
            describe_play_in_spanish(_play("field_out", description="Grounds out, shortstop to first base.", rbi=1)),
            "Jonathan Guzmán se retira con rodado y remolca 1 carrera.",
        )

    def test_jugada_de_corrido_sin_bateador(self):
        jugada = {"result": {"eventType": "stolen_base", "rbi": 0}, "about": {"isComplete": True}, "matchup": {}}
        self.assertEqual(describe_play_in_spanish(jugada), "Base robada.")

    def test_tipo_de_jugada_no_cubierto_devuelve_none(self):
        """Mejor mostrar la jugada original en inglés que inventarla."""
        self.assertIsNone(describe_play_in_spanish(_play("mound_visit", description="Mound Visit.")))
        self.assertIsNone(describe_play_in_spanish(_play("no_play", description="No play.")))

    def test_sin_nombre_del_bateador_devuelve_none(self):
        jugada = {"result": {"eventType": "single", "rbi": 0}, "about": {"isComplete": True}, "matchup": {}}
        self.assertIsNone(describe_play_in_spanish(jugada))
        self.assertIsNone(describe_play_in_spanish(None))


class ExtractLiveSituationTest(unittest.TestCase):
    def _feed(self, plays):
        return {
            "liveData": {
                "linescore": {
                    "currentInning": 4,
                    "inningHalf": "Bottom",
                    "outs": 1,
                    "balls": 2,
                    "strikes": 1,
                    "offense": {"batter": {"fullName": "Maxwell Romero Jr."}},
                    "defense": {"pitcher": {"fullName": "Juan Mercedes"}},
                },
                "plays": {"allPlays": plays},
            }
        }

    def test_usa_la_ultima_jugada_terminada_y_no_el_turno_en_curso(self):
        """El turno en curso trae basura de relleno ("Mound Visit."); no debe mostrarse."""
        feed = self._feed(
            [
                _play("strikeout", batter="Vidal Bruján", description="Vidal Bruján called out on strikes."),
                _play("mound_visit", batter="José Barrero", description="Mound Visit.", is_complete=False),
            ]
        )
        situation = extract_live_situation(feed)

        self.assertEqual(situation["last_play"], "Vidal Bruján called out on strikes.")
        self.assertEqual(situation["last_play_es"], "Vidal Bruján se poncha.")
        self.assertEqual(situation["inning"], 4)
        self.assertEqual(situation["batter"], "Maxwell Romero Jr.")
        self.assertEqual(situation["pitcher"], "Juan Mercedes")

    def test_sin_jugadas_terminadas(self):
        feed = self._feed([_play("mound_visit", description="Mound Visit.", is_complete=False)])
        situation = extract_live_situation(feed)

        self.assertIsNone(situation["last_play"])
        self.assertIsNone(situation["last_play_es"])


if __name__ == "__main__":
    unittest.main()
