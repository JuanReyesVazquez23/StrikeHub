/**
 * Buscador de estadísticas: el usuario escribe un nombre (nunca un ID) y
 * elige de una lista de sugerencias reales, traídas de /stats/search.
 * El resultado se muestra como una tarjeta legible, no como JSON crudo.
 */
let searchDebounceTimer = null;
let selectedEntityType = 'team';
let isCompareMode = false;
let firstCompareSelection = null; // {id, label} del primer elemento elegido en modo comparación
// Contador anti-races: si el usuario escribe o cambia de pestaña mientras un
// fetch está en vuelo, la respuesta vieja se descarta en vez de pintar
// sugerencias del deporte/texto anterior.
let statsRequestSequence = 0;

function formatOutcomeLabel(outcomeCode) {
  return outcomeCode === 'W' ? t('stats.win') : t('stats.loss');
}

function renderCompareRow(labelKey, firstValue, secondValue) {
  return `
    <tr>
      <td class="compare-value">${esc(firstValue ?? '-')}</td>
      <td class="compare-label">${t(labelKey)}</td>
      <td class="compare-value">${esc(secondValue ?? '-')}</td>
    </tr>`;
}

function renderPlayerCompareCard(comparisonData) {
  const firstPlayer = comparisonData.player_a;
  const secondPlayer = comparisonData.player_b;
  const firstBatting = firstPlayer.batting_stats || {};
  const secondBatting = secondPlayer.batting_stats || {};
  const firstPitching = firstPlayer.pitching_stats || {};
  const secondPitching = secondPlayer.pitching_stats || {};
  const hasBatting = firstPlayer.batting_stats || secondPlayer.batting_stats;
  const hasPitching = firstPlayer.pitching_stats || secondPlayer.pitching_stats;

  return `
    <div class="stats-card">
      <div class="compare-header-row">
        <div class="compare-header-side">
          ${firstPlayer.team?.logo_url ? `<img src="${esc(safeImg(firstPlayer.team.logo_url))}" alt="" loading="lazy" decoding="async">` : ''}
          <h3>${esc(firstPlayer.full_name)}</h3>
          <span class="stats-subtitle">${firstPlayer.team ? esc(firstPlayer.team.name) : ''}</span>
        </div>
        <span class="compare-vs">VS</span>
        <div class="compare-header-side">
          ${secondPlayer.team?.logo_url ? `<img src="${esc(safeImg(secondPlayer.team.logo_url))}" alt="" loading="lazy" decoding="async">` : ''}
          <h3>${esc(secondPlayer.full_name)}</h3>
          <span class="stats-subtitle">${secondPlayer.team ? esc(secondPlayer.team.name) : ''}</span>
        </div>
      </div>
      ${
        hasBatting
          ? `<h4 class="stats-section-label">${t('stats.battingStats')}</h4>
        <table class="compare-table">
          ${renderCompareRow('stats.avg', firstBatting.avg, secondBatting.avg)}
          ${renderCompareRow('stats.homeRuns', firstBatting.home_runs, secondBatting.home_runs)}
          ${renderCompareRow('stats.hits', firstBatting.hits, secondBatting.hits)}
          ${renderCompareRow('stats.rbi', firstBatting.rbi, secondBatting.rbi)}
          ${renderCompareRow('stats.obp', firstBatting.obp, secondBatting.obp)}
          ${renderCompareRow('stats.ops', firstBatting.ops, secondBatting.ops)}
        </table>`
          : ''
      }
      ${
        hasPitching
          ? `<h4 class="stats-section-label">${t('stats.pitchingStats')}</h4>
        <table class="compare-table">
          ${renderCompareRow('stats.era', firstPitching.era, secondPitching.era)}
          ${renderCompareRow('stats.strikeouts', firstPitching.strikeouts, secondPitching.strikeouts)}
          ${renderCompareRow('stats.saves', firstPitching.saves, secondPitching.saves)}
        </table>`
          : ''
      }
      ${
        !hasBatting && !hasPitching
          ? `<p class="empty-state">${t('stats.noStatsYet')}</p>`
          : ''
      }
    </div>`;
}

function renderTeamCompareCard(comparisonData) {
  const firstTeam = comparisonData.team_a;
  const secondTeam = comparisonData.team_b;

  return `
    <div class="stats-card">
      <div class="compare-header-row">
        <div class="compare-header-side">
          ${firstTeam.logo_url ? `<img src="${esc(safeImg(firstTeam.logo_url))}" alt="" loading="lazy" decoding="async">` : ''}
          <h3>${esc(firstTeam.name)}</h3>
          <span class="stats-subtitle">${esc(firstTeam.league || '')}</span>
        </div>
        <span class="compare-vs">VS</span>
        <div class="compare-header-side">
          ${secondTeam.logo_url ? `<img src="${esc(safeImg(secondTeam.logo_url))}" alt="" loading="lazy" decoding="async">` : ''}
          <h3>${esc(secondTeam.name)}</h3>
          <span class="stats-subtitle">${esc(secondTeam.league || '')}</span>
        </div>
      </div>
      <table class="compare-table">
        ${renderCompareRow('stats.wins', firstTeam.record.wins, secondTeam.record.wins)}
        ${renderCompareRow('stats.losses', firstTeam.record.losses, secondTeam.record.losses)}
        ${renderCompareRow('stats.winPct', `${(firstTeam.record.win_pct * 100).toFixed(1)}%`, `${(secondTeam.record.win_pct * 100).toFixed(1)}%`)}
      </table>
    </div>`;
}

function renderTeamCard(teamProfile) {
  const recentResultsHtml = teamProfile.recent_results.length
    ? teamProfile.recent_results
        .map(
          (gameResult) => `
        <div class="stats-result-row">
          <span class="outcome-tag ${gameResult.outcome === 'W' ? 'win' : 'loss'}">${esc(formatOutcomeLabel(gameResult.outcome))}</span>
          <span>${esc(gameResult.rival)}</span>
          <span class="stats-mono">${esc(gameResult.score)}</span>
          <span class="stats-mono">${esc(gameResult.date)}</span>
        </div>`
        )
        .join('')
    : `<p class="empty-state">${t('stats.noRecentGames')}</p>`;

  return `
    <div class="stats-card">
      <div class="stats-card-header">
        ${teamProfile.logo_url ? `<img src="${esc(safeImg(teamProfile.logo_url))}" alt="" loading="lazy" decoding="async">` : ''}
        <div>
          <h3>${esc(teamProfile.name)}</h3>
          <span class="stats-subtitle">${esc(teamProfile.league || '')} ${teamProfile.division ? '· ' + esc(teamProfile.division) : ''}</span>
        </div>
      </div>
      <div class="stats-record-row">
        <div><strong>${teamProfile.record.wins}</strong><span>${t('stats.wins')}</span></div>
        <div><strong>${teamProfile.record.losses}</strong><span>${t('stats.losses')}</span></div>
        <div><strong>${(teamProfile.record.win_pct * 100).toFixed(1)}%</strong><span>${t('stats.winPct')}</span></div>
      </div>
      <h4 class="stats-section-label">${t('stats.recentResults')}</h4>
      ${recentResultsHtml}
    </div>`;
}

function renderBattingStatsBlock(battingStats) {
  if (!battingStats) return '';
  return `
    <h4 class="stats-section-label">${t('stats.battingStats')}</h4>
    <div class="stats-record-row stats-record-wrap">
      <div><strong>${battingStats.avg ?? '-'}</strong><span>${t('stats.avg')}</span></div>
      <div><strong>${battingStats.home_runs ?? 0}</strong><span>${t('stats.homeRuns')}</span></div>
      <div><strong>${battingStats.hits ?? 0}</strong><span>${t('stats.hits')}</span></div>
      <div><strong>${battingStats.rbi ?? 0}</strong><span>${t('stats.rbi')}</span></div>
      <div><strong>${battingStats.obp ?? '-'}</strong><span>${t('stats.obp')}</span></div>
      <div><strong>${battingStats.slg ?? '-'}</strong><span>${t('stats.slg')}</span></div>
      <div><strong>${battingStats.ops ?? '-'}</strong><span>${t('stats.ops')}</span></div>
      <div><strong>${battingStats.stolen_bases ?? 0}</strong><span>${t('stats.stolenBases')}</span></div>
    </div>`;
}

function renderPitchingStatsBlock(pitchingStats) {
  if (!pitchingStats) return '';
  return `
    <h4 class="stats-section-label">${t('stats.pitchingStats')}</h4>
    <div class="stats-record-row stats-record-wrap">
      <div><strong>${pitchingStats.wins ?? 0}-${pitchingStats.losses ?? 0}</strong><span>${t('stats.record')}</span></div>
      <div><strong>${pitchingStats.era ?? '-'}</strong><span>${t('stats.era')}</span></div>
      <div><strong>${pitchingStats.strikeouts ?? 0}</strong><span>${t('stats.strikeouts')}</span></div>
      <div><strong>${pitchingStats.saves ?? 0}</strong><span>${t('stats.saves')}</span></div>
      <div><strong>${pitchingStats.innings_pitched ?? '-'}</strong><span>${t('stats.inningsPitched')}</span></div>
      <div><strong>${pitchingStats.whip ?? '-'}</strong><span>WHIP</span></div>
    </div>`;
}

function renderPlayerCard(playerProfile) {
  const hasStatLines = playerProfile.batting_stats || playerProfile.pitching_stats;
  return `
    <div class="stats-card">
      <div class="stats-card-header">
        ${playerProfile.team?.logo_url ? `<img src="${esc(safeImg(playerProfile.team.logo_url))}" alt="" loading="lazy" decoding="async">` : ''}
        <div>
          <h3>${esc(playerProfile.full_name)}</h3>
          <span class="stats-subtitle">
            ${esc(playerProfile.position || '')} ${playerProfile.jersey_number ? '· #' + Number(playerProfile.jersey_number) : ''}
            ${playerProfile.team ? '· ' + esc(playerProfile.team.name) : ''}
          </span>
        </div>
      </div>
      ${renderBattingStatsBlock(playerProfile.batting_stats)}
      ${renderPitchingStatsBlock(playerProfile.pitching_stats)}
      ${!hasStatLines ? `<p class="empty-state">${t('stats.noStatsYet')}</p>` : ''}
    </div>`;
}

async function fetchSuggestions(searchText) {
  const suggestionsDropdown = document.getElementById('stats-suggestions');
  const requestSequence = ++statsRequestSequence;
  if (searchText.length < 2) {
    suggestionsDropdown.classList.add('hidden');
    return;
  }
  try {
    const searchResults = await api.get(`/stats/search?q=${encodeURIComponent(searchText)}&type=${selectedEntityType}&sport=baseball`);
    // Respuesta vieja (el usuario siguió escribiendo o cambió de pestaña):
    // se descarta sin tocar el DOM.
    if (requestSequence !== statsRequestSequence) return;
    if (document.getElementById('stats-query')?.value !== searchText) return;
    if (!searchResults.length) {
      suggestionsDropdown.innerHTML = `<div class="stats-suggestion-empty">${t('stats.noMatches')}</div>`;
      suggestionsDropdown.classList.remove('hidden');
      return;
    }
    suggestionsDropdown.innerHTML = searchResults
      .map(
        (resultItem) => `
        <button type="button" class="stats-suggestion-item" data-id="${Number(resultItem.id)}" data-type="${esc(resultItem.type)}" data-label="${esc(resultItem.label)}">
          ${resultItem.logo_url ? `<img src="${esc(safeImg(resultItem.logo_url))}" alt="" loading="lazy" decoding="async">` : ''}
          <span>${esc(resultItem.label)}</span>
          <small>${esc(resultItem.sublabel || '')}</small>
        </button>`
      )
      .join('');
    suggestionsDropdown.classList.remove('hidden');

    suggestionsDropdown.querySelectorAll('.stats-suggestion-item').forEach((suggestionButton) => {
      suggestionButton.addEventListener('click', () => selectStatsResult(suggestionButton.dataset.type, suggestionButton.dataset.id, suggestionButton.dataset.label));
    });
  } catch (_) {
    suggestionsDropdown.classList.add('hidden');
  }
}

async function selectStatsResult(entityType, entityId, entityLabel) {
  document.getElementById('stats-suggestions').classList.add('hidden');
  const resultContainer = document.getElementById('stats-result');
  const statusBanner = document.getElementById('stats-compare-status');
  const searchInput = document.getElementById('stats-query');

  if (isCompareMode) {
    if (!firstCompareSelection) {
      firstCompareSelection = { id: entityId, label: entityLabel };
      searchInput.value = '';
      statusBanner.classList.remove('hidden');
      const secondKey = selectedEntityType === 'team' ? 'stats.compareNowPickSecondTeam' : 'stats.compareNowPickSecond';
      statusBanner.textContent = `${t('stats.compareFirstPicked')}: ${entityLabel}. ${t(secondKey)}`;
      return;
    }

    resultContainer.innerHTML = `<p class="empty-state">${t('common.loading')}</p>`;
    try {
      const compareEndpoint = entityType === 'team' ? '/stats/teams/compare' : '/stats/players/compare';
      const comparisonData = await api.get(`${compareEndpoint}?id_a=${Number(firstCompareSelection.id)}&id_b=${Number(entityId)}`);
      resultContainer.innerHTML = entityType === 'team' ? renderTeamCompareCard(comparisonData) : renderPlayerCompareCard(comparisonData);
    } catch (loadError) {
      resultContainer.innerHTML = `<p class="empty-state">${esc(loadError.message)}</p>`;
    }
    firstCompareSelection = null;
    statusBanner.classList.add('hidden');
    return;
  }

  resultContainer.innerHTML = `<p class="empty-state">${t('common.loading')}</p>`;
  try {
    const profileData = await api.get(`/stats/${entityType}/${entityId}`);
    resultContainer.innerHTML = entityType === 'team' ? renderTeamCard(profileData) : renderPlayerCard(profileData);
  } catch (_) {
    resultContainer.innerHTML = `<p class="empty-state">${t('common.error')}</p>`;
  }
}

function resetStatsSearch() {
  clearTimeout(searchDebounceTimer);
  statsRequestSequence++; // invalida cualquier fetch en vuelo
  const searchInput = document.getElementById('stats-query');
  const suggestionsDropdown = document.getElementById('stats-suggestions');
  const resultContainer = document.getElementById('stats-result');
  const statusBanner = document.getElementById('stats-compare-status');
  const compareToggle = document.getElementById('stats-compare-toggle');

  if (searchInput) searchInput.value = '';
  if (suggestionsDropdown) suggestionsDropdown.classList.add('hidden');
  if (resultContainer) resultContainer.innerHTML = '';
  if (statusBanner) statusBanner.classList.add('hidden');
  if (compareToggle) compareToggle.checked = false;
  isCompareMode = false;
  firstCompareSelection = null;
}

function initStatsSearch() {
  const searchInput = document.getElementById('stats-query');
  const entityTypeSelect = document.getElementById('stats-type');
  const compareToggle = document.getElementById('stats-compare-toggle');
  const statusBanner = document.getElementById('stats-compare-status');
  if (!searchInput) return;

  searchInput.addEventListener('input', (inputEvent) => {
    clearTimeout(searchDebounceTimer);
    const inputValue = inputEvent.target.value;
    searchDebounceTimer = setTimeout(() => fetchSuggestions(inputValue), 300);
  });

  entityTypeSelect.addEventListener('change', (changeEvent) => {
    selectedEntityType = changeEvent.target.value;
    clearTimeout(searchDebounceTimer);
    statsRequestSequence++; // invalida cualquier fetch en vuelo (era del otro tipo)
    searchInput.value = '';
    document.getElementById('stats-suggestions').classList.add('hidden');
    searchInput.placeholder = t(selectedEntityType === 'team' ? 'stats.placeholderTeam' : 'stats.placeholderPlayer');

    // El toggle aplica a ambos tipos, pero nunca se cruzan entre sí
    // (comparar siempre es equipo-vs-equipo o jugador-vs-jugador).
    document.getElementById('stats-compare-toggle-label').textContent = t(
      selectedEntityType === 'team' ? 'stats.compareTeamsToggle' : 'stats.comparePlayersToggle'
    );
    compareToggle.checked = false;
    isCompareMode = false;
    firstCompareSelection = null;
    statusBanner.classList.add('hidden');
  });

  compareToggle.addEventListener('change', (toggleEvent) => {
    isCompareMode = toggleEvent.target.checked;
    firstCompareSelection = null;
    statusBanner.classList.add('hidden');
    document.getElementById('stats-result').innerHTML = '';
  });

  document.addEventListener('click', (clickEvent) => {
    if (!clickEvent.target.closest('.stats-autocomplete-wrap')) {
      document.getElementById('stats-suggestions').classList.add('hidden');
    }
  });
}
