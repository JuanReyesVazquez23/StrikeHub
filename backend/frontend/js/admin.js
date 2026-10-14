/**
 * Panel de administración mínimo: solo borra equipos incorrectos a mano.
 *
 * Gesto de entrada: 5 taps en el footer, sin ningún popup ni contraseña
 * nueva — tal cual se pidió. La protección real está en el backend
 * (get_current_admin_user, ver app/api/deps.py): si el usuario logueado no
 * está en ADMIN_USERNAMES, el panel simplemente no muestra nada útil y las
 * peticiones al backend responden 403. No hay una segunda contraseña; se
 * reutiliza la sesión que ya existe para favoritos/predicciones.
 */
const ADMIN_LEAGUE_KEYS = ['mlb'];

let footerTapCount = 0;
let footerTapResetTimer = null;

function toggleAdminPanel() {
  const adminPanel = document.getElementById('admin-panel');
  if (!adminPanel) return;
  // Si quien toca no es el admin (o no ha iniciado sesión), los 5 taps no
  // hacen nada visible — nada distingue "no soy admin" de "no pasó nada".
  if (!window.currentUser?.is_admin) return;
  adminPanel.classList.toggle('hidden');
  if (!adminPanel.classList.contains('hidden')) {
    renderAdminLeagueOptions();
    loadAdminLeagues();
  }
}

function renderAdminLeagueOptions() {
  const leagueSelect = document.getElementById('admin-league-select');
  if (!leagueSelect || leagueSelect.dataset.filled) return;
  leagueSelect.innerHTML = ADMIN_LEAGUE_KEYS.map((leagueKey) => `<option value="${esc(leagueKey)}">${esc(leagueKey)}</option>`).join('');
  leagueSelect.dataset.filled = 'true';
}

async function loadAdminTeams() {
  const leagueSelect = document.getElementById('admin-league-select');
  const teamListContainer = document.getElementById('admin-team-list');
  if (!leagueSelect || !teamListContainer) return;

  teamListContainer.innerHTML = 'Cargando…';
  try {
    const teamRows = await api.get(`/admin/teams?league_key=${leagueSelect.value}`);
    if (!teamRows.length) {
      teamListContainer.innerHTML = '<p>No hay equipos en esta liga.</p>';
    } else {
      teamListContainer.innerHTML = teamRows
        .map(
          (teamRow) => `
        <div class="admin-team-row" data-team-id="${Number(teamRow.id)}">
          <span>
            ${esc(teamRow.name || '(sin nombre)')}
            ${teamRow.is_placeholder ? ' · placeholder' : ''}
            ${!teamRow.conference && !teamRow.division ? ' · sin conferencia/división' : ''}
          </span>
          <button class="btn btn-danger btn-small admin-delete-btn" data-team-id="${Number(teamRow.id)}" data-team-name="${esc(teamRow.name || '')}">
            Borrar
          </button>
        </div>`
        )
        .join('');

      teamListContainer.querySelectorAll('.admin-delete-btn').forEach((deleteButton) => {
        deleteButton.addEventListener('click', () => handleAdminDelete(deleteButton.dataset.teamId, deleteButton.dataset.teamName));
      });
    }
  } catch (loadError) {
    teamListContainer.innerHTML = `<p>${esc(loadError.message)}</p>`;
  }

  loadExcludedTeams();
}

async function loadExcludedTeams() {
  const leagueSelect = document.getElementById('admin-league-select');
  const excludedListContainer = document.getElementById('admin-excluded-list');
  if (!leagueSelect || !excludedListContainer) return;

  try {
    const excludedTeams = await api.get(`/admin/excluded-teams?league_key=${leagueSelect.value}`);
    if (!excludedTeams.length) {
      excludedListContainer.innerHTML = '';
      return;
    }
    excludedListContainer.innerHTML =
      '<h4 class="stats-section-label">Borrados (se pueden restaurar)</h4>' +
      excludedTeams
        .map(
          (excludedEntry) => `
      <div class="admin-team-row">
        <span>${esc(excludedEntry.team_name || excludedEntry.external_id)}</span>
        <button class="btn btn-outline btn-small admin-restore-btn" data-excluded-id="${Number(excludedEntry.id)}">
          Restaurar
        </button>
      </div>`
        )
        .join('');

    excludedListContainer.querySelectorAll('.admin-restore-btn').forEach((restoreButton) => {
      restoreButton.addEventListener('click', () => handleAdminRestore(restoreButton.dataset.excludedId));
    });
  } catch (loadError) {
    excludedListContainer.innerHTML = `<p>${esc(loadError.message)}</p>`;
  }
}

async function handleAdminDelete(teamId, teamName) {
  const isConfirmed = window.confirm(
    `¿Borrar "${teamName}"? También borra sus partidos, jugadores y favoritos asociados. Puedes restaurarlo después desde "Borrados" si te equivocas.`
  );
  if (!isConfirmed) return;

  try {
    await api.delete(`/admin/teams/${teamId}`);
    loadAdminTeams();
  } catch (deleteError) {
    window.alert(deleteError.message);
  }
}

async function handleAdminRestore(excludedId) {
  try {
    await api.delete(`/admin/excluded-teams/${excludedId}`);
    window.alert('Restaurado. Puede tardar hasta 5 minutos en volver a aparecer (la próxima sincronización lo recrea).');
    loadAdminTeams();
  } catch (restoreError) {
    window.alert(restoreError.message);
  }
}

async function loadAdminLeagues() {
  const leaguesListContainer = document.getElementById('admin-leagues-list');
  if (!leaguesListContainer) return;

  leaguesListContainer.innerHTML = 'Cargando…';
  try {
    const leagueRows = await api.get('/admin/leagues');
    leaguesListContainer.innerHTML = leagueRows
      .map(
        (leagueRow) => `
      <div class="admin-team-row">
        <span>
          ${esc(leagueRow.name)} · ${Number(leagueRow.team_count)} equipo(s)
          ${!leagueRow.sync_enabled ? ' · <strong>borrada</strong>' : ''}
        </span>
        ${
          leagueRow.sync_enabled
            ? `<button class="btn btn-danger btn-small admin-delete-league-btn" data-league-key="${esc(leagueRow.key)}" data-league-name="${esc(leagueRow.name)}">Borrar liga</button>`
            : `<button class="btn btn-outline btn-small admin-enable-league-btn" data-league-key="${esc(leagueRow.key)}">Reactivar</button>`
        }
      </div>`
      )
      .join('');

    leaguesListContainer.querySelectorAll('.admin-delete-league-btn').forEach((deleteButton) => {
      deleteButton.addEventListener('click', () => handleDeleteLeague(deleteButton.dataset.leagueKey, deleteButton.dataset.leagueName));
    });
    leaguesListContainer.querySelectorAll('.admin-enable-league-btn').forEach((enableButton) => {
      enableButton.addEventListener('click', () => handleEnableLeague(enableButton.dataset.leagueKey));
    });
  } catch (loadError) {
    leaguesListContainer.innerHTML = `<p>${esc(loadError.message)}</p>`;
  }
}

async function handleDeleteLeague(leagueKey, leagueName) {
  const isConfirmed = window.confirm(
    `¿Borrar TODA la liga "${leagueName}"? Esto borra todos sus equipos, partidos, jugadores y favoritos, y detiene su sincronización automática (útil para un evento ya pasado). Se puede reactivar después desde este mismo panel.`
  );
  if (!isConfirmed) return;

  try {
    await api.delete(`/admin/leagues/${leagueKey}`);
    loadAdminLeagues();
  } catch (deleteError) {
    window.alert(deleteError.message);
  }
}

async function handleEnableLeague(leagueKey) {
  try {
    await api.post(`/admin/leagues/${leagueKey}/enable`, {});
    window.alert('Reactivada. Sus datos se vuelven a sincronizar solos en los próximos minutos.');
    loadAdminLeagues();
  } catch (enableError) {
    window.alert(enableError.message);
  }
}

function initAdminPanel() {
  const footer = document.getElementById('app-footer');
  const loadButton = document.getElementById('admin-load-btn');
  if (footer) {
    footer.addEventListener('click', () => {
      footerTapCount += 1;
      clearTimeout(footerTapResetTimer);
      footerTapResetTimer = setTimeout(() => {
        footerTapCount = 0;
      }, 2000);
      if (footerTapCount >= 5) {
        footerTapCount = 0;
        toggleAdminPanel();
      }
    });
  }
  if (loadButton) loadButton.addEventListener('click', loadAdminTeams);
}

document.addEventListener('DOMContentLoaded', initAdminPanel);
