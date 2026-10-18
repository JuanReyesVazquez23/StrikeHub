/**
 * Orquesta la interfaz principal de StrikeHub (béisbol: MLB y LIDOM):
 * renderizado de posiciones, "jugadores hoy" (pitchers probables), noticias
 * y partidos (en vivo / finalizados / próximos con barra de probabilidad).
 */

/**
 * El sitio tiene dos ligas intercambiables con el selector de la barra
 * superior. activeLeague guarda la liga activa, es la que consumen todas las
 * vistas y además conserva la fecha elegida entre re-renders.
 */
const LEAGUE_KEY = 'mlb'; // liga por defecto (primera visita)
const SPORT_KEY = 'baseball';
const SUPPORTED_LEAGUES = ['mlb', 'lidom'];
// Clave de localStorage donde se recuerda la liga elegida, para que al volver
// el usuario encuentre la misma que estaba viendo.
const LEAGUE_STORAGE_KEY = 'bfb_active_league';
// Vistas exclusivas de MLB: el bracket tiene formato AL/NL (LIDOM usa otro
// formato) y los líderes de la Stats API mezclan TODAS las ligas invernales.
// Se ocultan cuando la liga activa es LIDOM.
const MLB_ONLY_VIEWS = new Set(['postseason', 'leaders']);
let activeLeague = readStoredLeague();

/* ---------------------- Liga recordada (localStorage) ---------------------- */

function readStoredLeague() {
  try {
    const storedLeague = localStorage.getItem(LEAGUE_STORAGE_KEY);
    if (SUPPORTED_LEAGUES.includes(storedLeague)) return storedLeague;
  } catch (_) {
    /* localStorage puede estar bloqueado (modo privado): se usa el valor por defecto */
  }
  return LEAGUE_KEY;
}

function storeLeague(leagueKey) {
  try {
    localStorage.setItem(LEAGUE_STORAGE_KEY, leagueKey);
  } catch (_) {
    /* silencioso: recordar la liga es una comodidad, no algo crítico */
  }
}

/* ---------------------- Selector de liga (MLB / LIDOM) ----------------------
   Cambia la liga activa de TODAS las vistas. Las vistas exclusivas de MLB
   (postemporada y líderes) se ocultan al elegir LIDOM. */

function updateLeagueChrome() {
  document.querySelectorAll('#league-switch .league-switch-btn').forEach((leagueButton) => {
    const isActive = leagueButton.dataset.league === activeLeague;
    leagueButton.classList.toggle('active', isActive);
    leagueButton.setAttribute('aria-pressed', String(isActive));
  });

  document.querySelectorAll('.view-tab').forEach((navTab) => {
    if (MLB_ONLY_VIEWS.has(navTab.dataset.view)) {
      navTab.classList.toggle('hidden', activeLeague !== 'mlb');
    }
  });

  const taglineElement = document.querySelector('.tagline');
  if (taglineElement) taglineElement.textContent = t(`tagline.${activeLeague}`);
  document.title = t(`titles.${activeLeague}`);

  // El título de la sección de noticias también cambia con la liga (la MLB
  // muestra las noticias generales del béisbol; la LIDOM, las de su liga).
  const newsTitleElement = document.getElementById('news-section-title');
  if (newsTitleElement) {
    newsTitleElement.textContent = t(activeLeague === 'lidom' ? 'sections.newsLidom' : 'sections.generalNews');
  }
}

async function refreshTickerForLeague() {
  // El ticker está arriba de toda la página: al cambiar de liga hay que
  // repintarlo aunque la vista activa no sea "En vivo" ni "Calendario".
  try {
    const { visibleGames } = await fetchDisplayGames(activeLeague);
    renderTicker(visibleGames);
  } catch (_) {
    /* silencioso: el ticker no es crítico */
  }
}

function setActiveLeague(leagueKey) {
  if (!SUPPORTED_LEAGUES.includes(leagueKey) || leagueKey === activeLeague) return;
  activeLeague = leagueKey;
  storeLeague(leagueKey);
  stopLivePolling();
  stopPostseasonPolling();

  const dateFilterInput = document.getElementById('games-date-input');
  if (dateFilterInput) dateFilterInput.value = '';

  updateLeagueChrome();
  refreshTickerForLeague();
  // Si la vista actual no existe en la nueva liga (postemporada / líderes),
  // se vuelve a "En vivo" en vez de quedar en una sección oculta.
  const nextView = MLB_ONLY_VIEWS.has(activeView) ? 'live' : activeView;
  loadedViews.clear();
  showView(nextView);
}

function initLeagueSelector() {
  // Dos botones separados (MLB / LIDOM): un clic cambia la liga activa.
  document.querySelectorAll('#league-switch .league-switch-btn').forEach((leagueButton) => {
    leagueButton.addEventListener('click', () => setActiveLeague(leagueButton.dataset.league));
  });
}

function formatDate(isoTimestamp) {
  return new Date(isoTimestamp).toLocaleString(i18nState.lang === 'es' ? 'es-ES' : 'en-US', {
    dateStyle: 'medium',
    timeStyle: 'short',
  });
}

/* ---------------------- Posiciones ---------------------- */
async function renderStandings(leagueKey) {
  const standingsContainer = document.getElementById('standings-container');
  standingsContainer.innerHTML = `<p class="empty-state">${t('common.loading')}</p>`;
  try {
    const divisionGroups = await api.get(`/leagues/${leagueKey}/standings`);
    if (!divisionGroups.length || !divisionGroups.some((divisionGroup) => divisionGroup.teams.length)) {
      standingsContainer.innerHTML = `<p class="empty-state">${t('common.standingsUnavailable')}</p>`;
      return;
    }

    standingsContainer.innerHTML = divisionGroups
      .map((divisionGroup) => {
        const tableRows = divisionGroup.teams
          .map(
            (teamRow) => `
            <tr>
              <td>
                <div class="team-cell">
                  <button class="fav-star" data-fav-type="team" data-fav-id="${Number(teamRow.id)}" aria-label="favorito">★</button>
                  ${teamRow.logo_url ? `<img src="${esc(safeImg(teamRow.logo_url))}" alt="" loading="lazy" decoding="async">` : ''}
                  ${esc(teamRow.name)}
                </div>
              </td>
              <td>${Number(teamRow.wins)}</td>
              <td>${Number(teamRow.losses)}</td>
              <td>${teamRow.games_back === 0 ? '-' : esc(teamRow.games_back)}</td>
            </tr>`
          )
          .join('');
        return `
          <h3 class="standings-group-title">${esc(divisionGroup.group_name)}</h3>
          <table class="standings-table">
            <thead>
              <tr><th>${t('stats.team')}</th><th>G</th><th>P</th><th>GB</th></tr>
            </thead>
            <tbody>${tableRows}</tbody>
          </table>`;
      })
      .join('');

    markFavoriteStars(standingsContainer);
  } catch (_) {
    standingsContainer.innerHTML = `<p class="empty-state">${t('common.error')}</p>`;
  }
}

/* ---------------------- Jugadores hoy (pitchers probables) ---------------------- */
async function renderPlayersToday(leagueKey) {
  const playersContainer = document.getElementById('players-today-container');
  playersContainer.innerHTML = `<p class="empty-state">${t('common.loading')}</p>`;
  try {
    const scheduledGames = await api.get(`/leagues/${leagueKey}/games?status=scheduled`);

    if (!scheduledGames.length) {
      playersContainer.innerHTML = `<p class="empty-state">${t('common.noGamesToday')}</p>`;
      return;
    }

    // Se pide el detalle de cada juego para leer los pitchers probables.
    const gameDetails = await Promise.all(scheduledGames.slice(0, 6).map((scheduledGame) => api.get(`/games/${scheduledGame.id}`)));

    playersContainer.innerHTML = gameDetails
      .map((gameDetail) => {
        const homeStarter = gameDetail.details?.home_pitcher || '—';
        const awayStarter = gameDetail.details?.away_pitcher || '—';
        return `
        <div class="player-card">
          <div>
            <div class="name">${esc(gameDetail.away_team.name)} @ ${esc(gameDetail.home_team.name)}</div>
            <div class="role">${t('game.probablePitcher')}: ${esc(awayStarter)} vs ${esc(homeStarter)}</div>
          </div>
        </div>`;
      })
      .join('');
  } catch (_) {
    playersContainer.innerHTML = `<p class="empty-state">${t('common.error')}</p>`;
  }
}

/* ---------------------- Noticias ---------------------- */
async function renderNews(sportKey, leagueKey) {
  const newsContainer = document.getElementById('news-container');
  newsContainer.innerHTML = `<p class="empty-state">${t('common.loading')}</p>`;
  try {
    // sort=trending: prioriza noticias sobre equipos de los que hay más
    // cobertura reciente (relevancia real por menciones), no solo la más nueva.
    // Se piden las noticias de la liga activa (ej. LIDOM); si esa liga todavía
    // no tiene noticias propias, el backend responde con las generales del
    // deporte, así que la sección nunca queda vacía por eso.
    const newsEndpoint = leagueKey ? `/news/league/${leagueKey}` : `/news/${sportKey}`;
    const newsArticles = await api.get(`${newsEndpoint}?sort=trending&lang=${i18nState.lang}`);
    if (!newsArticles.length) {
      newsContainer.innerHTML = `<p class="empty-state">${t('common.newsEmpty')}</p>`;
      return;
    }
    newsContainer.innerHTML = newsArticles
      .map(
        (article) => `
        <article class="card news-card">
          ${article.image_url ? `<img src="${esc(safeImg(article.image_url))}" alt="" loading="lazy" decoding="async">` : ''}
          <div class="card-body">
            <div class="news-meta">
              ${t('common.source')}: ${esc(article.source)} · ${esc(formatDate(article.published_at))}
            </div>
            <h3>${esc(article.title)}</h3>
            ${article.summary ? `<p>${esc(article.summary)}</p>` : ''}
            <a class="btn btn-outline btn-small" href="${esc(safeUrl(article.article_url))}" target="_blank" rel="noopener noreferrer">${t('common.readMore')}</a>
          </div>
        </article>`
      )
      .join('');
  } catch (_) {
    newsContainer.innerHTML = `<p class="empty-state">${t('common.error')}</p>`;
  }
}

/* ---------------------- Partidos: en vivo / finalizados / próximos ---------------------- */
function gameStatusLabel(scheduledGame) {
  if (scheduledGame.status === 'live') {
    // period_status ya lo calcula el backend (ej. "Inning 7" en MLB). Si algún
    // día no viene (otras ligas todavía sin ese dato), solo se muestra "En vivo".
    const periodSuffix = scheduledGame.period_status ? ` · ${esc(scheduledGame.period_status)}` : '';
    return `<span class="game-status live">● ${t('game.live')}${periodSuffix}</span>`;
  }
  if (scheduledGame.status === 'final') return `<span class="game-status">${t('game.final')}</span>`;
  return `<span class="game-status">${t('game.scheduled')}</span>`;
}

function renderGameDetailsBlock(scheduledGame) {
  if (scheduledGame.status !== 'final' || !scheduledGame.details) return '';
  const gameDetails = scheduledGame.details;
  const detailRows = [];
  if (gameDetails.winning_pitcher) detailRows.push(`${t('game.winningPitcher')}: ${esc(gameDetails.winning_pitcher)}`);
  if (gameDetails.losing_pitcher) detailRows.push(`${t('game.losingPitcher')}: ${esc(gameDetails.losing_pitcher)}`);
  if (gameDetails.save_pitcher) detailRows.push(`${t('game.savePitcher')}: ${esc(gameDetails.save_pitcher)}`);
  if (!detailRows.length) return '';

  return `<div class="game-details-box">${detailRows.join(' · ')}</div>`;
}

async function renderPredictionRow(scheduledGame) {
  if (scheduledGame.status !== 'scheduled') return '';

  const homeWinProbability = scheduledGame.home_win_probability ?? 0.5;
  const awayWinProbability = 1 - homeWinProbability;

  const probabilityBarHtml = `
    <div class="probability-wrap">
      <div class="probability-bar">
        <div class="probability-fill-home" style="width:${(homeWinProbability * 100).toFixed(0)}%"></div>
        <div class="probability-fill-away" style="width:${(awayWinProbability * 100).toFixed(0)}%"></div>
      </div>
      <div class="probability-labels">
        <span>${esc(scheduledGame.home_team.abbreviation || scheduledGame.home_team.name)} ${(homeWinProbability * 100).toFixed(0)}%</span>
        <span>${(awayWinProbability * 100).toFixed(0)}% ${esc(scheduledGame.away_team.abbreviation || scheduledGame.away_team.name)}</span>
      </div>
    </div>`;

  if (!window.currentUser) {
    return `${probabilityBarHtml}
      <div class="predict-row">
        <button class="btn btn-outline btn-small" data-open-auth="login">${t('game.loginToPredict')}</button>
      </div>`;
  }

  const homeWinPoints = estimateWinPoints(homeWinProbability);
  const awayWinPoints = estimateWinPoints(awayWinProbability);
  const homeLossPoints = estimateLossPoints(homeWinProbability);
  const awayLossPoints = estimateLossPoints(awayWinProbability);

  return `${probabilityBarHtml}
    <div class="predict-row">
      <button class="predict-btn" data-game-id="${Number(scheduledGame.id)}" data-team-id="${Number(scheduledGame.home_team.id)}">
        ${esc(scheduledGame.home_team.name)}
        <span class="points-tag points-tag-win">+${Number(homeWinPoints)}</span>
        <span class="points-tag points-tag-loss">-${Number(homeLossPoints)} ${t('game.ifWrong')}</span>
      </button>
      <button class="predict-btn" data-game-id="${Number(scheduledGame.id)}" data-team-id="${Number(scheduledGame.away_team.id)}">
        ${esc(scheduledGame.away_team.name)}
        <span class="points-tag points-tag-win">+${Number(awayWinPoints)}</span>
        <span class="points-tag points-tag-loss">-${Number(awayLossPoints)} ${t('game.ifWrong')}</span>
      </button>
    </div>`;
}

// Debe reflejar exactamente _apply_points_curve en app/services/probability_service.py
function applyPointsCurve(probability, curveStrength = 1.8) {
  const centered = (probability - 0.5) * 2;
  const direction = centered >= 0 ? 1 : -1;
  const curved = direction * Math.pow(Math.abs(centered), 1 / curveStrength);
  return Math.max(0, Math.min(1, curved / 2 + 0.5));
}

// Debe reflejar exactamente points_for_prediction en app/services/probability_service.py
function estimateWinPoints(probability) {
  const MIN_POINTS = 2, MAX_POINTS = 20;
  const points = MAX_POINTS - (MAX_POINTS - MIN_POINTS) * applyPointsCurve(probability);
  return Math.round(Math.max(MIN_POINTS, Math.min(MAX_POINTS, points)));
}

// Debe reflejar exactamente points_lost_for_prediction en app/services/probability_service.py
function estimateLossPoints(probability) {
  const MIN_POINTS = 2, MAX_POINTS = 20;
  const points = MIN_POINTS + (MAX_POINTS - MIN_POINTS) * applyPointsCurve(probability);
  return Math.round(Math.max(MIN_POINTS, Math.min(MAX_POINTS, points)));
}

function renderTicker(scheduledGames) {
  const tickerTrack = document.getElementById('ticker-track');
  if (!scheduledGames || !scheduledGames.length) {
    tickerTrack.innerHTML = `<span class="ticker-item">${t('common.tickerEmpty')}</span>`;
    return;
  }

  const tickerItems = scheduledGames
    .map((scheduledGame) => {
      const isFinalGame = scheduledGame.status === 'final';
      const scoreLabel = scheduledGame.status === 'scheduled' ? formatDate(scheduledGame.start_time) : `${scheduledGame.home_score ?? 0}-${scheduledGame.away_score ?? 0}`;
      const awayLogoHtml = scheduledGame.away_team.logo_url ? `<img src="${esc(safeImg(scheduledGame.away_team.logo_url))}" alt="" class="ticker-logo" loading="lazy" decoding="async">` : '';
      const homeLogoHtml = scheduledGame.home_team.logo_url ? `<img src="${esc(safeImg(scheduledGame.home_team.logo_url))}" alt="" class="ticker-logo" loading="lazy" decoding="async">` : '';
      return `
        <span class="ticker-item ${isFinalGame ? 'final' : ''}">
          <span class="ticker-dot"></span>
          ${awayLogoHtml}${esc(scheduledGame.away_team.abbreviation || scheduledGame.away_team.name)} @ ${homeLogoHtml}${esc(scheduledGame.home_team.abbreviation || scheduledGame.home_team.name)} · ${esc(scoreLabel)}
        </span>`;
    })
    .join('');

  // Se duplica el contenido para lograr un scroll continuo sin salto (ver @keyframes ticker-scroll).
  tickerTrack.innerHTML = tickerItems + tickerItems;
}

function scoreDisplay(scheduledGame) {
  // No mostrar marcador numérico en partidos que aún no comienzan: la API
  // devuelve 0 (no null) para esos casos, y 0-0 se confundía con un
  // partido realmente empatado en 0. Se decide por el status, no por el valor.
  if (scheduledGame.status === 'scheduled') return 'VS';
  return `${scheduledGame.home_score ?? 0} : ${scheduledGame.away_score ?? 0}`;
}

async function renderGameCard(scheduledGame) {
  const predictionRowHtml = await renderPredictionRow(scheduledGame);
  const liveSituationSlot = scheduledGame.status === 'live' ? `<div class="live-situation-slot" data-game-id="${Number(scheduledGame.id)}"></div>` : '';
  return `
    <div class="game-card">
      <div class="game-top-row">
        ${gameStatusLabel(scheduledGame)}
        <span class="game-status">${esc(formatDate(scheduledGame.start_time))}</span>
      </div>
      <div class="scoreboard-row">
        <div class="team-block home">
          ${scheduledGame.home_team.logo_url ? `<img src="${esc(safeImg(scheduledGame.home_team.logo_url))}" alt="" loading="lazy" decoding="async">` : ''}
          <span class="team-name">${esc(scheduledGame.home_team.name)}</span>
          <span class="team-role">${t('game.homeTeam')}</span>
        </div>
        <div class="score-led">${esc(scoreDisplay(scheduledGame))}</div>
        <div class="team-block away">
          ${scheduledGame.away_team.logo_url ? `<img src="${esc(safeImg(scheduledGame.away_team.logo_url))}" alt="" loading="lazy" decoding="async">` : ''}
          <span class="team-name">${esc(scheduledGame.away_team.name)}</span>
          <span class="team-role">${t('game.awayTeam')}</span>
        </div>
      </div>
      ${liveSituationSlot}
      ${renderGameDetailsBlock(scheduledGame)}
      ${predictionRowHtml}
    </div>`;
}

async function renderGameGroup(titleKey, groupedGames) {
  if (!groupedGames.length) return '';
  const gameCards = await Promise.all(groupedGames.map(renderGameCard));
  return `
    <h3 class="game-group-title">${t(titleKey)}</h3>
    ${gameCards.join('')}`;
}

/* ---------- Situación en vivo (diamante, outs, última jugada) ---------- */
const LIVE_POLL_INTERVAL_MS = 15000; // "rápido, sin refresh manual" según lo pedido
let livePollTimers = [];

function renderDiamond(occupiedBases) {
  return `
    <div class="diamond-wrap">
      <div class="diamond">
        <div class="diamond-base second ${occupiedBases.second ? 'occupied' : ''}"></div>
        <div class="diamond-base third ${occupiedBases.third ? 'occupied' : ''}"></div>
        <div class="diamond-base first ${occupiedBases.first ? 'occupied' : ''}"></div>
        <div class="diamond-base home"></div>
      </div>
    </div>`;
}

function renderOuts(outCount) {
  const outDots = [0, 1, 2].map((dotIndex) => `<span class="out-dot ${dotIndex < outCount ? 'filled' : ''}"></span>`).join('');
  return `<div class="outs-row">${t('game.outs')}: ${outDots}</div>`;
}

function renderLiveSituationHtml(liveSituation) {
  if (!liveSituation) return '';
  const inningArrow = liveSituation.inning_half === 'Top' ? '▲' : '▼';
  return `
    <div class="live-situation">
      <div class="diamond-wrap">
        ${renderDiamond(liveSituation.bases)}
        ${renderOuts(liveSituation.outs)}
      </div>
      <div class="live-situation-info">
        <span>${inningArrow} ${t('game.inning')} ${liveSituation.inning ?? '-'}</span>
        <span class="count">${Number(liveSituation.balls ?? 0)}-${Number(liveSituation.strikes ?? 0)} · ${t('game.outs')} ${Number(liveSituation.outs ?? 0)}</span>
        ${liveSituation.batter ? `<span>${t('game.atBat')}: ${esc(liveSituation.batter)}</span>` : ''}
        ${liveSituation.pitcher ? `<span>${t('game.pitching')}: ${esc(liveSituation.pitcher)}</span>` : ''}
        ${liveSituation.last_play ? `<span class="last-play">${t('game.lastPlay')}: ${esc(liveSituation.last_play)}</span>` : ''}
      </div>
    </div>`;
}

async function refreshLiveSituation(liveGameId) {
  const liveSlot = document.querySelector(`.live-situation-slot[data-game-id="${liveGameId}"]`);
  if (!liveSlot) return; // la tarjeta ya no está en pantalla (cambiaron de liga/pestaña)

  try {
    const livePayload = await api.get(`/games/${liveGameId}/live?lang=${i18nState.lang}`);
    if (livePayload.status !== 'live') {
      liveSlot.innerHTML = ''; // el partido ya terminó: se quita el diamante en el siguiente refresh general
      return;
    }
    liveSlot.innerHTML = renderLiveSituationHtml(livePayload.situation);
  } catch (_) {
    // Si falla una consulta puntual no se rompe la tarjeta; se reintenta en el siguiente ciclo.
  }
}

function stopLivePolling() {
  livePollTimers.forEach((pollTimerId) => clearInterval(pollTimerId));
  livePollTimers = [];
}

function startLivePolling(liveGameIds) {
  stopLivePolling();
  liveGameIds.forEach((liveGameId) => {
    refreshLiveSituation(liveGameId); // primera carga inmediata, sin esperar el primer intervalo
    const pollTimerId = setInterval(() => refreshLiveSituation(liveGameId), LIVE_POLL_INTERVAL_MS);
    livePollTimers.push(pollTimerId);
  });
}

async function fetchDisplayGames(leagueKey, specificDate = null) {
  const dateQuery = specificDate ? `?game_date=${specificDate}` : '';
  const scheduledGames = await api.get(`/leagues/${leagueKey}/games${dateQuery}`);

  const todayIsoDate = new Date().toISOString().slice(0, 10);
  const isHistoricalSearch = Boolean(specificDate) && specificDate < todayIsoDate;

  // Si se busca una fecha pasada, se fuerza status='final' en una copia de
  // cada juego (sin mutar el original). Así toda la lógica de abajo
  // (etiqueta, si se muestra el diamante, agrupación) es consistente, sin
  // importar qué status haya quedado guardado por error en el backend.
  const visibleGames = isHistoricalSearch ? scheduledGames.map((visibleGame) => ({ ...visibleGame, status: 'final' })) : scheduledGames;
  return { visibleGames, isHistoricalSearch };
}

async function renderLiveSection(leagueKey) {
  const gamesContainer = document.getElementById('live-container');
  gamesContainer.innerHTML = `<p class="empty-state">${t('common.loading')}</p>`;
  try {
    const { visibleGames } = await fetchDisplayGames(leagueKey);
    renderTicker(visibleGames);

    const liveGames = visibleGames.filter((visibleGame) => visibleGame.status === 'live');
    const finalGames = visibleGames.filter((visibleGame) => visibleGame.status === 'final');

    if (!liveGames.length && !finalGames.length) {
      gamesContainer.innerHTML = `<p class="empty-state">${t('common.noGamesToday')}</p>`;
      stopLivePolling();
      return;
    }

    gamesContainer.innerHTML =
      (await renderGameGroup('sections.liveNow', liveGames)) +
      (await renderGameGroup('sections.finished', finalGames));
    startLivePolling(liveGames.map((liveGame) => liveGame.id));
  } catch (_) {
    gamesContainer.innerHTML = `<p class="empty-state">${t('common.error')}</p>`;
  }
}

async function renderCalendarSection(leagueKey, specificDate = null) {
  const calendarContainer = document.getElementById('calendar-container');
  calendarContainer.innerHTML = `<p class="empty-state">${t('common.loading')}</p>`;
  try {
    const { visibleGames, isHistoricalSearch } = await fetchDisplayGames(leagueKey, specificDate);
    if (!isHistoricalSearch) renderTicker(visibleGames);

    if (!visibleGames.length) {
      calendarContainer.innerHTML = `<p class="empty-state">${t('common.noGamesToday')}</p>`;
      return;
    }

    const upcomingGames = visibleGames.filter((visibleGame) => visibleGame.status === 'scheduled');
    const finalGames = visibleGames.filter((visibleGame) => visibleGame.status === 'final');
    const gameGroupsHtml = specificDate
      ? (await renderGameGroup('sections.finished', finalGames)) +
        (await renderGameGroup('sections.upcoming', upcomingGames))
      : await renderGameGroup('sections.upcoming', upcomingGames);

    calendarContainer.innerHTML = gameGroupsHtml || `<p class="empty-state">${t('common.noGamesToday')}</p>`;
    attachPredictionHandlers(calendarContainer);
  } catch (_) {
    calendarContainer.innerHTML = `<p class="empty-state">${t('common.error')}</p>`;
  }
}

function attachPredictionHandlers(gamesContainer) {
  // Botón "inicia sesión para predecir" (reemplaza el onclick inline,
  // incompatible con CSP sin 'unsafe-inline').
  gamesContainer.querySelectorAll('[data-open-auth]').forEach((authButton) => {
    authButton.addEventListener('click', () => openAuthModal(authButton.dataset.openAuth || 'login'));
  });
  gamesContainer.querySelectorAll('.predict-btn').forEach((predictButton) => {
    predictButton.addEventListener('click', async () => {
      const targetGameId = Number(predictButton.dataset.gameId);
      const targetTeamId = Number(predictButton.dataset.teamId);
      try {
        await api.post('/predictions', { game_id: targetGameId, predicted_team_id: targetTeamId });
        predictButton.classList.add('chosen');
        predictButton.disabled = true;
        const siblingButtons = predictButton.parentElement.querySelectorAll('.predict-btn');
        siblingButtons.forEach((siblingButton) => { if (siblingButton !== predictButton) siblingButton.disabled = true; });
      } catch (predictError) {
        if (typeof showToast === 'function') showToast(predictError.message, 'error');
        else alert(predictError.message);
      }
    });
  });
}

/* ---------------------- Postemporada (bracket) ----------------------
   Cuadro dibujado en SVG (como el "Panorama de la Postemporada" de MLB):
   Liga Americana a la izquierda, Nacional a la derecha y la Serie Mundial
   al centro. Los datos vienen de GET /postseason/bracket (siempre 5 series
   por liga + la Serie Mundial; un equipo null = por definir). */
const BRACKET_GEOMETRY = {
  nodeRadius: 31, // semi-diagonal del rombo de cada equipo
  width: 1000,
  height: 664,
  columns: [60, 172, 284, 396],
  centerX: 500,
  centerY: 355,
};
const POSTSEASON_REFRESH_MS = 60000;
let postseasonRefreshTimer = null;

function stopPostseasonPolling() {
  if (postseasonRefreshTimer) {
    clearInterval(postseasonRefreshTimer);
    postseasonRefreshTimer = null;
  }
}

function startPostseasonPolling() {
  stopPostseasonPolling();
  postseasonRefreshTimer = setInterval(() => {
    if (document.hidden || activeView !== 'postseason') return;
    renderPostseason(true);
  }, POSTSEASON_REFRESH_MS);
}

function sanitizeBracketColor(colorValue) {
  return /^#[0-9a-fA-F]{3,8}$/.test(colorValue || '') ? colorValue : '#3d3d43';
}

function diamondPoints(centerX, centerY, radius) {
  return `${centerX},${centerY - radius} ${centerX + radius},${centerY} ${centerX},${centerY + radius} ${centerX - radius},${centerY}`;
}

/* Un equipo (rombo con logo, sembrado y victorias) o un rombo vacío. */
function renderBracketNode(bracketNode) {
  const { team, x, y, showWins } = bracketNode;
  const nodeRadius = bracketNode.r || BRACKET_GEOMETRY.nodeRadius;
  if (!team) {
    return `<polygon class="ps-diamond ps-empty" points="${diamondPoints(x, y, nodeRadius)}"><title>${esc(t('postseason.tbd'))}</title></polygon>`;
  }
  const nodeClass = `ps-node${team.eliminated ? ' ps-out' : ''}${team.is_winner ? ' ps-win' : ''}`;
  const logoUrl = safeImg(team.logo_url);
  const logoSize = nodeRadius * 1.2;
  const nodeInner = logoUrl
    ? `<image href="${esc(logoUrl)}" x="${x - logoSize / 2}" y="${y - logoSize / 2}" width="${logoSize}" height="${logoSize}" preserveAspectRatio="xMidYMid meet"/>`
    : `<text class="ps-abbr" x="${x}" y="${y}">${esc(team.abbreviation || '')}</text>`;
  const seedBadge = team.seed != null
    ? `<g class="ps-seed"><circle cx="${x - nodeRadius * 0.62}" cy="${y - nodeRadius * 0.62}" r="9"/><text x="${x - nodeRadius * 0.62}" y="${y - nodeRadius * 0.62}">${esc(team.seed)}</text></g>`
    : '';
  const winsBadge = showWins
    ? `<g class="ps-wins"><rect x="${x + nodeRadius * 0.32}" y="${y + nodeRadius * 0.32}" width="22" height="19" rx="5"/><text x="${x + nodeRadius * 0.32 + 11}" y="${y + nodeRadius * 0.32 + 10}">${Number(team.wins)}</text></g>`
    : '';
  const nodeTitle = `${team.name || team.abbreviation}${team.seed != null ? ` · #${team.seed}` : ''}${showWins ? ` · ${Number(team.wins)}` : ''}`;
  return `<g class="${nodeClass}"><title>${esc(nodeTitle)}</title>
    <polygon class="ps-diamond" stroke="${sanitizeBracketColor(team.color)}" points="${diamondPoints(x, y, nodeRadius)}"/>
    ${nodeInner}${seedBadge}${winsBadge}</g>`;
}

/* Líneas en codo desde cada entrada hasta el nodo de la serie siguiente. */
function renderBracketConnectors(sourceNodes, targetNode, direction, series) {
  const nodeRadius = BRACKET_GEOMETRY.nodeRadius;
  const endX = targetNode.x - direction * nodeRadius;
  const connectorPaths = sourceNodes.map((sourceNode) => {
    const startX = sourceNode.x + direction * nodeRadius;
    const midX = (startX + endX) / 2;
    const winnerClass = sourceNode.team && sourceNode.team.is_winner ? ' win' : '';
    return `<path class="ps-line${winnerClass}" d="M${startX} ${sourceNode.y} H${midX} V${targetNode.y} H${endX}"/>`;
  });
  const firstStartX = sourceNodes[0].x + direction * nodeRadius;
  const liveDot = series && series.status === 'live'
    ? `<circle class="ps-live-dot" cx="${(firstStartX + endX) / 2}" cy="${targetNode.y}" r="4.5"/>`
    : '';
  return connectorPaths.join('') + liveDot;
}

function hasSeriesStarted(series) {
  return !!series && ['live', 'in_progress', 'final'].includes(series.status);
}

/* Un lado del cuadro (direction = 1 liga Americana, -1 liga Nacional, espejo). */
function renderBracketSide(leagueCode, seriesList, worldSeries, direction) {
  const findSlot = (slotName) => seriesList.find((series) => series.slot === slotName);
  const wildcardA = findSlot('WC_A'), wildcardB = findSlot('WC_B'), divisionA = findSlot('DS_A'), divisionB = findSlot('DS_B'), championship = findSlot('CS');
  if (!wildcardA || !wildcardB || !divisionA || !divisionB || !championship || !worldSeries) return '';
  const columnX = (columnIndex) => (direction > 0 ? BRACKET_GEOMETRY.columns[columnIndex] : BRACKET_GEOMETRY.width - BRACKET_GEOMETRY.columns[columnIndex]);
  const centerY = BRACKET_GEOMETRY.centerY;
  const makeNode = (series, teamIndex, column, y) => ({ team: series.teams[teamIndex], x: columnX(column), y, showWins: hasSeriesStarted(series) });

  const wildcardA0 = makeNode(wildcardA, 0, 0, 95), wildcardA1 = makeNode(wildcardA, 1, 0, 185);
  const wildcardB0 = makeNode(wildcardB, 0, 0, 415), wildcardB1 = makeNode(wildcardB, 1, 0, 505);
  const divisionA0 = makeNode(divisionA, 0, 1, 140), divisionA1 = makeNode(divisionA, 1, 1, 250);
  const divisionB0 = makeNode(divisionB, 0, 1, 460), divisionB1 = makeNode(divisionB, 1, 1, 570);
  const championship0 = makeNode(championship, 0, 2, 195), championship1 = makeNode(championship, 1, 2, 515);
  const worldSeriesIndex = direction > 0 ? 0 : 1;
  const worldSeriesNode = makeNode(worldSeries, worldSeriesIndex, 3, centerY);

  const connectorLines =
    renderBracketConnectors([wildcardA0, wildcardA1], divisionA0, direction, wildcardA) +
    renderBracketConnectors([wildcardB0, wildcardB1], divisionB0, direction, wildcardB) +
    renderBracketConnectors([divisionA0, divisionA1], championship0, direction, divisionA) +
    renderBracketConnectors([divisionB0, divisionB1], championship1, direction, divisionB) +
    renderBracketConnectors([championship0, championship1], worldSeriesNode, direction, championship);
  const sideNodes = [wildcardA0, wildcardA1, wildcardB0, wildcardB1, divisionA0, divisionA1, divisionB0, divisionB1, championship0, championship1, worldSeriesNode].map(renderBracketNode).join('');

  const midpoint = (columnA, columnB) => (columnX(columnA) + columnX(columnB)) / 2;
  const renderSideLabel = (x, mainLabel, subLabel) =>
    `<text class="ps-label" x="${x}" y="634">${esc(mainLabel)}</text><text class="ps-sub" x="${x}" y="650">${esc(subLabel)}</text>`;
  const formatBestOf = (seriesLength) => `${t('postseason.bestOf')} ${seriesLength}`;
  const sideLabels =
    renderSideLabel(midpoint(0, 1), t('postseason.WC').toUpperCase(), formatBestOf(wildcardA.best_of)) +
    renderSideLabel(midpoint(1, 2), `${leagueCode}DS`, formatBestOf(divisionA.best_of)) +
    renderSideLabel(midpoint(2, 3), `${leagueCode}CS`, formatBestOf(championship.best_of));
  const leagueTitle = `<text class="ps-league" x="${direction > 0 ? 30 : BRACKET_GEOMETRY.width - 30}" y="30" text-anchor="${direction > 0 ? 'start' : 'end'}">${esc(t(`postseason.${leagueCode}`).toUpperCase())}</text>`;

  return `<g>${connectorLines}${sideNodes}${sideLabels}${leagueTitle}</g>`;
}

/* Centro: Serie Mundial y campeón. */
function renderBracketCenter(worldSeries, seasonYear) {
  const centerX = BRACKET_GEOMETRY.centerX, centerY = BRACKET_GEOMETRY.centerY;
  const champion = (worldSeries.teams || []).find((finalist) => finalist && finalist.is_winner) || null;
  const centerRadius = 46;
  const leftFinalist = worldSeries.teams[0], rightFinalist = worldSeries.teams[1];
  const connectorPaths = [
    `<path class="ps-line${leftFinalist && leftFinalist.is_winner ? ' win' : ''}" d="M${BRACKET_GEOMETRY.columns[3] + BRACKET_GEOMETRY.nodeRadius} ${centerY} H${centerX - centerRadius}"/>`,
    `<path class="ps-line${rightFinalist && rightFinalist.is_winner ? ' win' : ''}" d="M${BRACKET_GEOMETRY.width - BRACKET_GEOMETRY.columns[3] - BRACKET_GEOMETRY.nodeRadius} ${centerY} H${centerX + centerRadius}"/>`,
    worldSeries.status === 'live' ? `<circle class="ps-live-dot" cx="${centerX - centerRadius - 18}" cy="${centerY}" r="4.5"/><circle class="ps-live-dot" cx="${centerX + centerRadius + 18}" cy="${centerY}" r="4.5"/>` : '',
  ].join('');
  const championNode = champion
    ? renderBracketNode({ team: { ...champion, eliminated: false, is_winner: true }, x: centerX, y: centerY, r: centerRadius, showWins: false })
    : `<polygon class="ps-diamond ps-empty ps-ws-empty" points="${diamondPoints(centerX, centerY, centerRadius)}"><title>${esc(t('postseason.WS'))}</title></polygon>`;

  const scoreLine = hasSeriesStarted(worldSeries) && leftFinalist && rightFinalist
    ? `${esc(leftFinalist.abbreviation)} ${Number(leftFinalist.wins)} – ${Number(rightFinalist.wins)} ${esc(rightFinalist.abbreviation)}`
    : '';
  const captionBlock = champion
    ? `<text class="ps-label ps-champ" x="${centerX}" y="${centerY + centerRadius + 28}">${esc(t('postseason.champion').toUpperCase())}</text>
       <text class="ps-sub" x="${centerX}" y="${centerY + centerRadius + 46}">${esc(champion.name || champion.abbreviation)}</text>`
    : `<text class="ps-sub" x="${centerX}" y="${centerY + centerRadius + 28}">${esc(t('postseason.bestOf'))} ${Number(worldSeries.best_of)}</text>`;
  return `<g>${connectorPaths}
    <text class="ps-ws-title" x="${centerX}" y="${centerY - centerRadius - 40}">${esc(t('postseason.WS').toUpperCase())}</text>
    <text class="ps-sub" x="${centerX}" y="${centerY - centerRadius - 20}">${esc(seasonYear)}</text>
    ${championNode}
    ${scoreLine ? `<text class="ps-label" x="${centerX}" y="${centerY + centerRadius + (champion ? 66 : 48)}">${scoreLine}</text>` : ''}
    ${captionBlock}</g>`;
}

function buildBracketSvg(bracketData) {
  const worldSeries = bracketData.world_series;
  if (!worldSeries) return '';
  return `<svg class="ps-svg" viewBox="0 0 ${BRACKET_GEOMETRY.width} ${BRACKET_GEOMETRY.height}" role="img" aria-label="${esc(t('postseason.aria'))}" xmlns="http://www.w3.org/2000/svg">
    ${renderBracketSide('AL', bracketData.al || [], worldSeries, 1)}
    ${renderBracketSide('NL', bracketData.nl || [], worldSeries, -1)}
    ${renderBracketCenter(worldSeries, bracketData.season)}
  </svg>`;
}

async function renderPostseason(silent = false) {
  const postseasonContainer = document.getElementById('postseason-container');
  if (!postseasonContainer) return;
  if (!silent) postseasonContainer.innerHTML = `<p class="empty-state">${t('common.loading')}</p>`;
  try {
    const bracketData = await api.get('/postseason/bracket');
    if (!bracketData.postseason_active) {
      stopPostseasonPolling();
      postseasonContainer.innerHTML = `<p class="empty-state">${t('postseason.notActive')}</p>`;
      return;
    }
    const previousScroller = postseasonContainer.querySelector('.ps-scroll');
    const previousScrollLeft = previousScroller ? previousScroller.scrollLeft : null;

    const updatedTimeLabel = bracketData.updated_at
      ? new Date(bracketData.updated_at).toLocaleTimeString(i18nState.lang === 'es' ? 'es-ES' : 'en-US', { hour: '2-digit', minute: '2-digit' })
      : '';
    const championCard = bracketData.champion;
    postseasonContainer.innerHTML = `
      <div class="ps-head">
        <h3 class="ps-title">${esc(t('postseason.title'))} <small>${esc(bracketData.season)}</small></h3>
        <div class="ps-meta">
          ${bracketData.stale ? `<span class="ps-stale">${esc(t('postseason.stale'))}</span> · ` : ''}${updatedTimeLabel ? `${esc(t('postseason.updated'))} ${esc(updatedTimeLabel)}` : ''}
        </div>
      </div>
      ${championCard ? `<div class="ps-champion">🏆 ${esc(t('postseason.champion'))}: ${championCard.logo_url ? `<img src="${esc(safeImg(championCard.logo_url))}" alt="" decoding="async">` : ''}<strong>${esc(championCard.name || championCard.abbreviation)}</strong></div>` : ''}
      <p class="ps-hint">${esc(t('postseason.scrollHint'))}</p>
      <div class="ps-scroll">${buildBracketSvg(bracketData)}</div>`;

    const scrollerElement = postseasonContainer.querySelector('.ps-scroll');
    if (scrollerElement) {
      scrollerElement.scrollLeft = previousScrollLeft != null ? previousScrollLeft : Math.max(0, (scrollerElement.scrollWidth - scrollerElement.clientWidth) / 2);
    }
    startPostseasonPolling();
  } catch (_) {
    // En una actualización silenciosa se conserva el cuadro que ya estaba en pantalla.
    if (!silent || !postseasonContainer.querySelector('.ps-scroll')) {
      postseasonContainer.innerHTML = `<p class="empty-state">${t('common.error')}</p>`;
    }
  }
}

/* ---------------------- Líderes de la temporada ----------------------
   Contenido de offseason: tablas de líderes de bateo y pitcheo con datos
   reales de MLB Stats API (ver GET /stats/leaders). */
const LEADER_LABEL_KEY_BY_CATEGORY = {
  homeRuns: 'stats.homeRuns',
  runsBattedIn: 'stats.rbi',
  stolenBases: 'stats.stolenBases',
  wins: 'stats.wins',
  earnedRunAverage: 'stats.era',
  strikeouts: 'stats.strikeouts',
  saves: 'stats.saves',
};

function renderLeaderTable(categoryKey, leaderEntries) {
  const leaderRows = (leaderEntries || [])
    .map(
      (leaderEntry) => `
      <div class="leader-row">
        <span class="leader-rank">${leaderEntry.rank != null ? esc(leaderEntry.rank) : ''}</span>
        <span class="leader-name">${esc(leaderEntry.name)}</span>
        <span class="leader-team">${esc(leaderEntry.team)}</span>
        <span class="leader-value">${esc(leaderEntry.value)}</span>
      </div>`
    )
    .join('');
  return `
    <div class="leader-card">
      <h4 class="leader-title">${esc(t(LEADER_LABEL_KEY_BY_CATEGORY[categoryKey] || categoryKey))}</h4>
      ${leaderRows || `<p class="empty-state">${t('common.noGamesToday')}</p>`}
    </div>`;
}

async function renderLeaders() {
  const leadersContainer = document.getElementById('leaders-container');
  leadersContainer.innerHTML = `<p class="empty-state">${t('common.loading')}</p>`;
  try {
    const leadersPayload = await api.get('/stats/leaders');
    const leaderGroups = leadersPayload.groups || {};
    const battingGroups = leaderGroups.hitting || {};
    const pitchingGroups = leaderGroups.pitching || {};
    leadersContainer.innerHTML = `
      <h3 class="leaders-group-title">${esc(leadersPayload.season)} · ${esc(t('stats.battingStats'))}</h3>
      <div class="leaders-grid">
        ${Object.entries(battingGroups).map(([categoryKey, leaderEntries]) => renderLeaderTable(categoryKey, leaderEntries)).join('')}
      </div>
      <h3 class="leaders-group-title">${esc(leadersPayload.season)} · ${esc(t('stats.pitchingStats'))}</h3>
      <div class="leaders-grid">
        ${Object.entries(pitchingGroups).map(([categoryKey, leaderEntries]) => renderLeaderTable(categoryKey, leaderEntries)).join('')}
      </div>`;
  } catch (_) {
    leadersContainer.innerHTML = `<p class="empty-state">${t('common.error')}</p>`;
  }
}

/* ---------------------- Favoritos ---------------------- */
async function markFavoriteStars(gamesContainer) {
  if (!window.currentUser) return;
  try {
    const storedFavorites = await api.get('/favorites/me');
    gamesContainer.querySelectorAll('.fav-star').forEach((favoriteStar) => {
      const favoriteType = favoriteStar.dataset.favType;
      const favoriteTargetId = Number(favoriteStar.dataset.favId);
      const matchingFavorite = storedFavorites.find((storedFavorite) => storedFavorite.favorite_type === favoriteType && storedFavorite[`${favoriteType}_id`] === favoriteTargetId);
      if (matchingFavorite) {
        favoriteStar.classList.add('active');
        favoriteStar.dataset.favoriteRecordId = matchingFavorite.id;
      }
      favoriteStar.addEventListener('click', () => toggleFavorite(favoriteStar, favoriteType, favoriteTargetId));
    });
  } catch (_) {
    /* silencioso: si falla, simplemente no se marcan estrellas */
  }
}

async function toggleFavorite(starButton, favoriteType, targetId) {
  if (!window.currentUser) {
    openAuthModal('login');
    return;
  }
  try {
    if (starButton.classList.contains('active')) {
      await api.delete(`/favorites/${starButton.dataset.favoriteRecordId}`);
      starButton.classList.remove('active');
    } else {
      const createdFavorite = await api.post('/favorites', { favorite_type: favoriteType, target_id: targetId });
      starButton.dataset.favoriteRecordId = createdFavorite.id;
      starButton.classList.add('active');
    }
  } catch (favoriteError) {
    if (typeof showToast === 'function') showToast(favoriteError.message, 'error');
    else alert(favoriteError.message);
  }
}

/* ---------------------- Vistas (una sección a la vez) ----------------------
   La página se divide en vistas con botones: En vivo, Calendario,
   Posiciones, Postemporada, Noticias y Estadísticas. Cada vista carga su
   contenido la primera vez que se muestra (rápido al entrar: solo En vivo).
   La vista de noticias incluye el complemento "Jugadores Hoy". */
const loadedViews = new Set();
let activeView = 'live';

const VIEW_LOADERS = {
  live: () => renderLiveSection(activeLeague),
  calendar: () => renderCalendarSection(activeLeague, document.getElementById('games-date-input')?.value || null),
  standings: () => renderStandings(activeLeague),
  postseason: () => renderPostseason(),
  leaders: () => renderLeaders(),
  news: () => Promise.all([renderNews(SPORT_KEY, activeLeague), renderPlayersToday(activeLeague)]),
  stats: () => Promise.resolve(),
};

function showView(viewName) {
  if (!VIEW_LOADERS[viewName]) return;
  // Postemporada y líderes no existen en LIDOM: si por alguna razón se pide
  // una de esas vistas con LIDOM activo, se muestra "En vivo" en su lugar.
  if (MLB_ONLY_VIEWS.has(viewName) && activeLeague !== 'mlb') viewName = 'live';
  activeView = viewName;
  document.querySelectorAll('.view-tab').forEach((navTab) => {
    navTab.classList.toggle('active', navTab.dataset.view === viewName);
  });
  document.querySelectorAll('[data-view-section]').forEach((viewSection) => {
    viewSection.classList.toggle('hidden', viewSection.dataset.viewSection !== viewName);
  });
  // El polling en vivo solo tiene sentido en su vista.
  if (viewName !== 'live') stopLivePolling();
  if (viewName !== 'postseason') stopPostseasonPolling();
  if (loadedViews.has(viewName)) {
    if (viewName === 'live') renderLiveSection(activeLeague);
    // El cuadro de postemporada cambia con cada juego: se actualiza al volver (sin parpadeo si ya estaba dibujado).
    if (viewName === 'postseason') renderPostseason(!!document.querySelector('#postseason-container .ps-scroll'));
    return;
  }
  loadedViews.add(viewName);
  VIEW_LOADERS[viewName]();
}

function initViewNav() {
  document.querySelectorAll('.view-tab').forEach((navTab) => {
    navTab.addEventListener('click', () => showView(navTab.dataset.view));
  });
}

function initDateSearch() {
  const dateFilterInput = document.getElementById('games-date-input');
  const clearDateButton = document.getElementById('games-date-today');

  dateFilterInput.addEventListener('change', (changeEvent) => {
    if (changeEvent.target.value) renderCalendarSection(activeLeague, changeEvent.target.value);
  });

  clearDateButton.addEventListener('click', () => {
    dateFilterInput.value = '';
    renderCalendarSection(activeLeague);
  });
}

async function loadMainContent() {
  resetStatsSearch();
  activeLeague = readStoredLeague();
  updateLeagueChrome();
  const dateFilterInput = document.getElementById('games-date-input');
  if (dateFilterInput) dateFilterInput.value = '';
  loadedViews.clear();
  showView('live');
}

document.addEventListener('bfb:language-changed', () => {
  // Recarga la vista actual en el nuevo idioma; las demás se recargarán
  // cuando se visiten (loadedViews se limpia). updateLeagueChrome() repinta
  // la cabecera (título/lema) porque el idioma cambió.
  loadedViews.clear();
  updateLeagueChrome();
  showView(activeView);
});

// Tras login/logout/registro el estado de usuario cambia: las tarjetas ya
// pintadas (botones de predecir, estrellas de favorito) quedarían con el
// estado anterior. Se re-renderizan las vistas cargadas que dependen de
// la sesión (noticias/stats no).
document.addEventListener('bfb:user-changed', () => {
  if (!activeLeague) return;
  if (loadedViews.has('live')) renderLiveSection(activeLeague);
  if (loadedViews.has('calendar')) {
    const dateFilterInput = document.getElementById('games-date-input');
    renderCalendarSection(activeLeague, dateFilterInput?.value || null);
  }
  if (loadedViews.has('standings')) renderStandings(activeLeague);
});

async function initApp() {
  await initI18n();
  initAuth();
  initLeagueSelector();
  initViewNav();
  initDateSearch();
  initStatsSearch();
  await loadMainContent();
}

document.addEventListener('DOMContentLoaded', initApp);
