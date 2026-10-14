/**
 * Historial de predicciones del usuario y aviso de resultados nuevos.
 *
 * Cómo funciona el aviso: cada predicción tiene un campo "seen". Al
 * resolverse (cuando el partido termina), el backend la marca seen=false.
 * Cada vez que el usuario entra o refresca con sesión iniciada, se revisa
 * el historial buscando resultados con seen=false, se muestra un aviso
 * flotante por cada uno, y se marcan como vistos para no repetir el aviso.
 */

function showToast(message, kind = 'info') {
  const toastContainer = document.getElementById('toast-container');
  if (!toastContainer) return;

  const toastElement = document.createElement('div');
  toastElement.className = `toast toast-${kind}`;
  toastElement.textContent = message;
  toastContainer.appendChild(toastElement);

  setTimeout(() => toastElement.classList.add('toast-visible'), 10);
  setTimeout(() => {
    toastElement.classList.remove('toast-visible');
    setTimeout(() => toastElement.remove(), 300);
  }, 6000);
}

function formatMatchup(prediction) {
  const scheduledGame = prediction.game;
  if (!scheduledGame || !scheduledGame.home_team || !scheduledGame.away_team) return '';
  return `${scheduledGame.away_team.name} @ ${scheduledGame.home_team.name}`;
}

async function checkForNewPredictionResults() {
  let storedPredictions;
  try {
    storedPredictions = await api.get('/predictions/me');
  } catch (_) {
    return; // sin sesión válida u otro error: no interrumpe el resto de la página
  }

  const unseenResults = storedPredictions.filter((prediction) => prediction.status !== 'pending' && !prediction.seen);
  if (!unseenResults.length) return;

  unseenResults.forEach((prediction) => {
    const matchupLabel = formatMatchup(prediction);
    if (prediction.status === 'correct') {
      showToast(`¡Ganaste! Acertaste ${prediction.predicted_team?.name || 'tu equipo'} en ${matchupLabel} (+${prediction.points_awarded} puntos Strike)`, 'success');
    } else {
      showToast(`Perdiste tu predicción de ${prediction.predicted_team?.name || ''} en ${matchupLabel} (${prediction.points_awarded} puntos Strike)`, 'error');
    }
  });

  api.post('/predictions/me/mark-seen', { prediction_ids: unseenResults.map((prediction) => prediction.id) }).catch(() => {});
}

function renderPredictionHistoryRow(prediction) {
  const matchupLabel = formatMatchup(prediction);
  const scheduledGame = prediction.game;
  const finalScore = scheduledGame && scheduledGame.status === 'final' ? `${scheduledGame.away_score} - ${scheduledGame.home_score}` : '';

  let pointsBadge = '';
  if (prediction.status === 'correct') {
    pointsBadge = `<span class="points-pill">+${prediction.points_awarded}</span>`;
  } else if (prediction.status === 'incorrect') {
    pointsBadge = `<span class="points-pill points-pill-loss">${prediction.points_awarded}</span>`;
  }

  const rowStatusClass = { pending: '', correct: 'prediction-correct', incorrect: 'prediction-incorrect' }[prediction.status] || '';

  return `
    <div class="prediction-row ${rowStatusClass}">
      <div>
        <strong>${esc(prediction.predicted_team?.name || '—')}</strong>
        <span class="stats-subtitle">${esc(matchupLabel)} ${finalScore ? '· ' + esc(finalScore) : ''}</span>
      </div>
      <div class="prediction-row-status">
        ${pointsBadge}
        <button class="prediction-delete-btn" data-prediction-id="${Number(prediction.id)}" aria-label="Borrar">&times;</button>
      </div>
    </div>`;
}

function renderPredictionsSection(sectionTitle, predictionList) {
  if (!predictionList.length) return '';
  return `<h4 class="stats-section-label">${sectionTitle} (${predictionList.length})</h4>${predictionList.map(renderPredictionHistoryRow).join('')}`;
}

function groupPredictionsByStatus(storedPredictions) {
  return {
    pending: storedPredictions.filter((prediction) => prediction.status === 'pending'),
    correct: storedPredictions.filter((prediction) => prediction.status === 'correct'),
    incorrect: storedPredictions.filter((prediction) => prediction.status === 'incorrect'),
  };
}

async function openPredictionsModal() {
  const modalBackdrop = document.getElementById('predictions-modal-backdrop');
  const listContainer = document.getElementById('predictions-list');
  if (!modalBackdrop || !listContainer) return;

  modalBackdrop.classList.remove('hidden');
  listContainer.innerHTML = 'Cargando…';

  try {
    const storedPredictions = await api.get('/predictions/me');
    renderPredictionsListInto(listContainer, storedPredictions);
  } catch (loadError) {
    listContainer.innerHTML = `<p class="empty-state">${esc(loadError.message)}</p>`;
  }
}

function renderPredictionsListInto(listContainer, storedPredictions) {
  if (!storedPredictions.length) {
    listContainer.innerHTML = '<p class="empty-state">Todavía no has hecho ninguna predicción.</p>';
    return;
  }

  const groupedPredictions = groupPredictionsByStatus(storedPredictions);
  listContainer.innerHTML = `
    <div class="predictions-summary">
      <span>${groupedPredictions.pending.length} pendientes</span>
      <span class="prediction-correct">${groupedPredictions.correct.length} ganadas</span>
      <span class="prediction-incorrect">${groupedPredictions.incorrect.length} perdidas</span>
    </div>
    ${renderPredictionsSection('Pendientes', groupedPredictions.pending)}
    ${renderPredictionsSection('Ganadas', groupedPredictions.correct)}
    ${renderPredictionsSection('Perdidas', groupedPredictions.incorrect)}
  `;

  listContainer.querySelectorAll('.prediction-delete-btn').forEach((deleteButton) => {
    deleteButton.addEventListener('click', () => handleDeletePrediction(deleteButton.dataset.predictionId, listContainer));
  });
}

async function handleDeletePrediction(predictionId, listContainer) {
  try {
    await api.delete(`/predictions/${predictionId}`);
    const storedPredictions = await api.get('/predictions/me');
    renderPredictionsListInto(listContainer, storedPredictions);
  } catch (deleteError) {
    window.alert(deleteError.message);
  }
}

function closePredictionsModal() {
  document.getElementById('predictions-modal-backdrop')?.classList.add('hidden');
}

function initPredictionsModal() {
  document.getElementById('predictions-modal-close')?.addEventListener('click', closePredictionsModal);
  document.getElementById('predictions-modal-backdrop')?.addEventListener('click', (clickEvent) => {
    if (clickEvent.target.id === 'predictions-modal-backdrop') closePredictionsModal();
  });
}

document.addEventListener('DOMContentLoaded', initPredictionsModal);
