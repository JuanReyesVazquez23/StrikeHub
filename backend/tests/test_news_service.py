"""
Pruebas del recorte de resúmenes de noticias (sin red, sin servidor).

Ejecutar desde backend/:
    python -m pytest tests/ -q
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.news_service import _summarize_first_sentence  # noqa: E402


class SummarizeFirstSentenceTest(unittest.TestCase):
    def test_corta_en_el_primer_punto(self):
        texto = (
            "Oscar de la Cruz lanzó cinco entradas en blanco y las Estrellas Orientales conectaron tres "
            "cuadrangulares para derrotar 11-0 a los Toros del Este. Después sigue una explicación larga "
            "que no debe verse en la tarjeta."
        )
        self.assertEqual(
            _summarize_first_sentence(texto),
            "Oscar de la Cruz lanzó cinco entradas en blanco y las Estrellas Orientales conectaron tres "
            "cuadrangulares para derrotar 11-0 a los Toros del Este.",
        )

    def test_limpia_el_espacio_que_deja_el_html_antes_del_punto(self):
        texto = "Las Estrellas ganaron el partido inaugural . Y luego una frase larga que sobra ."
        self.assertEqual(
            _summarize_first_sentence(texto),
            "Las Estrellas ganaron el partido inaugural.",
        )

    def test_no_corta_en_abreviaturas_ni_decimales(self):
        texto = "El promedio subió a 11.5 carreras por juego en EE.UU. y siguió subiendo toda la semana."
        self.assertEqual(
            _summarize_first_sentence(texto),
            "El promedio subió a 11.5 carreras por juego en EE.UU. y siguió subiendo toda la semana.",
        )

    def test_ignora_una_abreviatura_al_principio(self):
        texto = "Dr. Pérez dirigió el partido . Después vino una explicación larguísima que tampoco debe verse ."
        self.assertEqual(_summarize_first_sentence(texto), "Dr. Pérez dirigió el partido.")

    def test_sin_punto_final_devuelve_el_texto_completo(self):
        texto = "Resumen corto sin punto final"
        self.assertEqual(_summarize_first_sentence(texto), texto)

    def test_vacio_y_none(self):
        self.assertIsNone(_summarize_first_sentence(None))
        self.assertEqual(_summarize_first_sentence(""), "")


if __name__ == "__main__":
    unittest.main()
