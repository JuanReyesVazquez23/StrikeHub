# ⚾ StrikeHub

<p align="center">
  <img src="backend/frontend/assets/logos/strikehub-logo.svg" alt="StrikeHub" width="359">
</p>

## Website Online:
https://strikehub.onrender.com (Render Free Plan)

<p align="center">
  <strong>La casa del béisbol: MLB y LIDOM en vivo, predicciones, estadísticas y noticias.</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white"/>
  <img src="https://img.shields.io/badge/PostgreSQL-336791?style=for-the-badge&logo=postgresql&logoColor=white"/>
  <img src="https://img.shields.io/badge/SQLAlchemy-D71F00?style=for-the-badge"/>
  <img src="https://img.shields.io/badge/JavaScript-F7DF1E?style=for-the-badge&logo=javascript&logoColor=black"/>
  <img src="https://img.shields.io/badge/HTML5-E34F26?style=for-the-badge&logo=html5&logoColor=white"/>
  <img src="https://img.shields.io/badge/CSS3-1572B6?style=for-the-badge&logo=css3&logoColor=white"/>
</p>

---

## 📖 About

**StrikeHub** es una aplicación web dedicada al béisbol: **MLB** (Grandes Ligas) y **LIDOM** (Liga de Béisbol Profesional de la República Dominicana, temporada invernal) con un selector de liga que cambia todas las vistas. Marcadores en vivo (con diamante, outs y última jugada), pitchers probables, posiciones, estadísticas reales de bateo/pitcheo, noticias y un sistema de predicciones con puntos Strike.

> Antes cubría fútbol y basketball, pero sus APIs gratuitas eran inestables e incompletas. La MLB Stats API (oficial, gratuita, sin key) es eficiente y clara — y además expone la LIDOM bajo el mismo servicio (`sportId=17`, `leagueId=131`) — así que la página se enfocó en béisbol.

---

## ✨ Features

- ⚾ Marcadores de **MLB y LIDOM** en vivo (diamante, conteo, última jugada)
- 🔀 Selector de liga (MLB / LIDOM): cambia todas las vistas
- 📅 Calendario y resultados con búsqueda por fecha (en la LIDOM, la temporada completa)
- 📊 Posiciones y estadísticas reales de bateo/pitcheo
- 🏆 Postemporada de MLB: cuadro en vivo (Wild Card → Serie Mundial) con sembrados, victorias por serie y campeón
- 🎯 Predicciones con puntos Strike, historial y avisos de ganaste/perdiste
- ❤️ Equipos favoritos
- 👤 Autenticación segura (JWT en cookie httpOnly)
- 🌎 Español / English
- 📰 Noticias (ESPN para la MLB; prensa dominicana para la LIDOM)
- 🛠️ Panel de administración

---

## 🛠️ Tech Stack

### Backend

- FastAPI
- SQLAlchemy
- PostgreSQL
- Pydantic
- JWT Authentication
- PyJWT

### Frontend

- HTML5
- CSS3
- JavaScript (sin framework)

### Datos

- **MLB Stats API** (oficial, gratuita, sin key): equipos, partidos, posiciones, rosters y stats. Sirve a la MLB (`sportId=1`) y a la LIDOM (`sportId=17`, `leagueId=131`).
- **ESPN RSS** (y prensa dominicana para la LIDOM): noticias con imagen

---

## 🔐 Security

- JWT Authentication (PyJWT)
- Password hashing con bcrypt
- HttpOnly Cookies + SameSite=Lax
- Content-Security-Policy + headers de seguridad
- Validación con Pydantic (cotas, patrones y rangos en todos los endpoints)
- Rate limiting (login/registro y endpoints costosos)
- Sanitización XSS en frontend (`esc()`/`safeUrl()`)
- SQL Injection protection through SQLAlchemy
- Secure CORS configuration (fail-fast en producción)

---

## 🚀 Project Goal

Ser el lugar más rápido y limpio para seguir el béisbol (MLB y LIDOM): abrir, ver el juego y predecir.

---

## 📈 Project Status

🚧 **Actively under development**

---

## ❤️ Built With

- FastAPI
- PostgreSQL
- SQLAlchemy
- Pydantic
- JavaScript

---

<p align="center">
Made by Juan Reyes
</p>

---

# 📚 Documentación técnica (setup, despliegue, arquitectura)

## Estado actual del proyecto

| Módulo | Estado |
|---|---|
| Backend (FastAPI + PostgreSQL) | ✅ Completo y funcional |
| Autenticación (registro/login, cookie httpOnly) | ✅ Completo |
| Sistema de puntos Strike (predicciones) | ✅ Completo |
| Historial de predicciones + aviso de ganaste/perdiste | ✅ Completo |
| Favoritos (equipo) | ✅ Completo |
| **MLB** — posiciones, pitchers hoy, en vivo, resultados, estadísticas reales | ✅ Funcional de extremo a extremo (MLB Stats API, gratuita, sin key) |
| **LIDOM** — posiciones, en vivo, resultados, calendario completo de la temporada, estadísticas reales (selector de liga) | ✅ Funcional de extremo a extremo (misma MLB Stats API, `sportId=17`) |
| Noticias (ESPN para la MLB; prensa dominicana para la LIDOM) | ✅ Funcional |
| Panel de administración (MLB y LIDOM) | ✅ Completo |
| PWA / "instalar app" | ✅ Básico |

## Seguridad implementada

- Contraseñas con **bcrypt**.
- Sesión con **JWT en cookie httpOnly + SameSite=Lax**.
- **CORS restringido** a orígenes explícitos (falla al arrancar en prod si es permisivo).
- **CSP + headers** (X-Frame-Options, nosniff, HSTS en prod); `/docs` desactivado en producción.
- Todo acceso a datos vía **ORM de SQLAlchemy**.
- **Rate limiting** en login/registro y endpoints costosos (`/games/live`, `/stats/*`).
- Mensajes de error genéricos en login (no revela si el usuario existe).
- Validación de entradas con Pydantic en todos los endpoints.
- Panel de administración protegido por sesión + `ADMIN_USERNAMES`.
- Secretos solo en `.env`, nunca en el código ni en el repositorio.

## Cómo ejecutarlo localmente

```bash
createdb bfb_deportes
cd backend
python -m venv venv
source venv/bin/activate        # En Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
python -c "import secrets; print(secrets.token_hex(32))"   # para SECRET_KEY

uvicorn app.main:app --reload
```

Abre **http://localhost:8000**. La primera vez sincroniza MLB, LIDOM y noticias, y se repite cada 5 minutos en segundo plano.

### Variables de entorno relevantes (`.env`)

- `SECRET_KEY` — obligatoria en producción (32+ caracteres, si no la app no arranca).
- `ADMIN_USERNAMES` — tu(s) username(s) con acceso al panel, separados por coma.
- `DATABASE_URL` — conexión PostgreSQL.
- `CORS_ORIGINS` — orígenes permitidos.

## Despliegue

Actualmente en **Render** (plan gratis). El repo incluye `render.yaml` en la raíz. El plan gratis se "duerme" tras ~15 minutos sin tráfico; la sincronización solo corre mientras el servicio está despierto.

También se puede desplegar en **Railway** (Root Directory = `backend`).

## Estructura del proyecto

```
bfb-deportes/
└── backend/
    ├── app/
    │   ├── core/          # config, seguridad, base de datos, rate limit, migraciones ligeras
    │   ├── models/        # tablas SQLAlchemy (sport, prediction, user, favorite)
    │   ├── schemas/       # validación Pydantic
    │   ├── api/routes/    # auth, leagues, games, news, favorites, predictions, stats, admin
    │   ├── services/      # mlb_service, news_service, sync_service, probability_service, postseason_service, ...
    │   └── main.py
    ├── tests/             # pruebas sin red: python -m unittest discover -s tests
    ├── frontend/
    │   ├── index.html
    │   ├── manifest.json
    │   ├── assets/ (logos/ = logo SVG del header, icons/ = favicon y PNG de la PWA)
    │   ├── css/styles.css + modules/
    │   ├── js/ (api, i18n, auth, predictions, stats, main, admin, escape, pwa-install)
    │   └── i18n/ (es.json, en.json)
    ├── requirements.txt
    ├── render.yaml
    └── .env.example
```

## Próximos pasos sugeridos

1. Alembic para migraciones versionadas (ahora: migraciones ligeras + `create_all`).
2. Rate limiter con Redis si se despliega con varios workers.
3. Refresh tokens con rotación (hoy: access de 7 días sin revocación).
