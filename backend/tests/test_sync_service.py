"""
Pruebas del calendario completo de temporada (sin red, sin servidor).

Ejecutar desde backend/:
    python -m pytest tests/ -q
"""
import asyncio
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError

from app.services import mlb_service  # noqa: E402
from app.services import sync_service  # noqa: E402
from app.services.mlb_service import LIDOM_API_CONFIG, MLB_API_CONFIG  # noqa: E402
from app.services.sync_service import season_schedule_window  # noqa: E402


class FakeResponse:
    """Respuesta httpx falsa: un calendario sin días, que es todo lo que hace falta aquí."""

    def raise_for_status(self):
        return None

    def json(self):
        return {"dates": []}


class FakeAsyncClient:
    """Cliente httpx falso: guarda la petición y responde sin salir a la red."""

    last_request_url = None
    last_request_params = None

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def get(self, url, params=None):
        FakeAsyncClient.last_request_url = url
        FakeAsyncClient.last_request_params = params
        return FakeResponse()


class SeasonScheduleWindowTest(unittest.TestCase):
    def test_en_octubre_la_temporada_es_la_que_empieza_ese_ano(self):
        self.assertEqual(
            season_schedule_window(date(2026, 10, 18)),
            (date(2026, 9, 1), date(2027, 2, 28)),
        )

    def test_en_septiembre_ya_cuenta_la_temporada_nueva(self):
        self.assertEqual(
            season_schedule_window(date(2026, 9, 1)),
            (date(2026, 9, 1), date(2027, 2, 28)),
        )

    def test_en_enero_la_temporada_es_la_que_empezo_el_ano_anterior(self):
        self.assertEqual(
            season_schedule_window(date(2027, 1, 15)),
            (date(2026, 9, 1), date(2027, 2, 28)),
        )

    def test_de_marzo_a_agosto_la_ventana_queda_en_el_pasado(self):
        """Con la ventana en el pasado, la sincronización no pide nada: temporada muerta."""
        for reference_date in (date(2027, 3, 1), date(2027, 6, 15), date(2027, 8, 31)):
            with self.subTest(reference_date=reference_date):
                _, season_end_date = season_schedule_window(reference_date)
                self.assertLess(season_end_date, reference_date)


class LeagueScheduleConfigTest(unittest.TestCase):
    def test_la_lidom_sincroniza_la_temporada_completa(self):
        self.assertTrue(LIDOM_API_CONFIG.sync_full_season_schedule)

    def test_la_mlb_no_sincroniza_la_temporada_completa(self):
        self.assertFalse(MLB_API_CONFIG.sync_full_season_schedule)


class ScheduleRangeTest(unittest.TestCase):
    """get_schedule_range debe pedir el rango de fechas y el filtro de liga correctos."""

    def setUp(self):
        patcher = mock.patch.object(mlb_service.httpx, "AsyncClient", FakeAsyncClient)
        patcher.start()
        self.addCleanup(patcher.stop)
        FakeAsyncClient.last_request_url = None
        FakeAsyncClient.last_request_params = None

    def test_get_schedule_de_un_dia_pide_ese_dia_en_los_dos_extremos(self):
        asyncio.run(mlb_service.get_schedule(date(2026, 10, 20), LIDOM_API_CONFIG))
        self.assertTrue(FakeAsyncClient.last_request_url.endswith("/schedule"))
        self.assertEqual(FakeAsyncClient.last_request_params["startDate"], "2026-10-20")
        self.assertEqual(FakeAsyncClient.last_request_params["endDate"], "2026-10-20")

    def test_pide_el_rango_completo_con_el_filtro_de_la_liga(self):
        asyncio.run(
            mlb_service.get_schedule_range(date(2026, 9, 1), date(2027, 2, 28), LIDOM_API_CONFIG)
        )
        self.assertEqual(FakeAsyncClient.last_request_params["startDate"], "2026-09-01")
        self.assertEqual(FakeAsyncClient.last_request_params["endDate"], "2027-02-28")
        self.assertEqual(FakeAsyncClient.last_request_params["sportId"], 17)
        self.assertEqual(FakeAsyncClient.last_request_params["leagueId"], "131")

    def test_la_mlb_no_manda_filtro_de_liga(self):
        asyncio.run(mlb_service.get_schedule_range(date(2026, 10, 20), date(2026, 10, 20), MLB_API_CONFIG))
        self.assertNotIn("leagueId", FakeAsyncClient.last_request_params)


class LeagueScheduleRaceTest(unittest.TestCase):
    """
    El cron y el sincronizador del sitio comparten base de datos: si los dos
    intentan crear el mismo partido nuevo, el que pierde la carrera no debe
    tumbar la corrida.
    """

    def test_reintenta_una_vez_si_choca_con_otra_sincronizacion(self):
        corridas = []

        async def sincronizacion_falsa(*args, **kwargs):
            corridas.append(args)
            if len(corridas) == 1:
                raise IntegrityError("INSERT INTO games", {}, Exception("duplicate key"))

        with mock.patch.object(sync_service, "_sync_league_games_once", sincronizacion_falsa):
            asyncio.run(sync_service.sync_league_games("mlb", MLB_API_CONFIG))

        self.assertEqual(len(corridas), 2)

    def test_no_reintenta_si_el_error_es_otro(self):
        corridas = []

        async def sincronizacion_falsa(*args, **kwargs):
            corridas.append(args)
            raise RuntimeError("la API se cayó")

        with mock.patch.object(sync_service, "_sync_league_games_once", sincronizacion_falsa):
            with self.assertRaises(RuntimeError):
                asyncio.run(sync_service.sync_league_games("mlb", MLB_API_CONFIG))

        self.assertEqual(len(corridas), 1)


class CronEntryPointTest(unittest.TestCase):
    """El cron debe poder arrancar sobre una base vacía, no solo sobre una ya migrada."""

    def test_prepara_la_base_antes_de_sincronizar(self):
        orden = []

        with (
            mock.patch.object(sync_service, "_prepare_database", lambda: orden.append("base")),
            mock.patch.object(
                sync_service, "run_full_sync", mock.AsyncMock(side_effect=lambda: orden.append("sync"))
            ),
        ):
            exit_code = sync_service.main()

        self.assertEqual(exit_code, 0)
        self.assertEqual(orden, ["base", "sync"])

    def test_prepara_una_base_vacia_crea_el_esquema(self):
        base_vacia = create_engine("sqlite://")

        with mock.patch.object(sync_service, "engine", base_vacia):
            sync_service._prepare_database()

        tablas = inspect(base_vacia).get_table_names()
        self.assertIn("sports", tablas)
        self.assertIn("games", tablas)


if __name__ == "__main__":
    unittest.main()
