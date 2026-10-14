/**
 * Autenticación en el frontend.
 *
 * IMPORTANTE: el token de sesión vive en una cookie httpOnly que el
 * backend coloca en /auth/login y /auth/register. Este archivo NUNCA lee
 * ni guarda el token; solo mantiene en memoria los datos públicos del
 * usuario (window.currentUser) para pintar la interfaz.
 */
window.currentUser = null;

function renderUserStatus() {
  const statusContainer = document.getElementById('user-status');
  if (!statusContainer) return;

  if (window.currentUser) {
    statusContainer.innerHTML = `
      <div class="account-menu">
        <button class="account-menu-toggle" id="account-menu-toggle">
          <span class="points-pill">${Number(window.currentUser.bfb_points)} pts</span>
          <span class="account-username">${esc(window.currentUser.username)}</span>
          <span class="account-menu-caret">▾</span>
        </button>
        <div class="account-menu-dropdown hidden" id="account-menu-dropdown">
          <button class="account-menu-item" id="predictions-history-btn">Mis predicciones</button>
          <button class="account-menu-item" id="logout-btn">${t('auth.logout')}</button>
        </div>
      </div>
    `;
    document.getElementById('account-menu-toggle').addEventListener('click', (clickEvent) => {
      clickEvent.stopPropagation();
      document.getElementById('account-menu-dropdown').classList.toggle('hidden');
    });
    document.getElementById('logout-btn').addEventListener('click', handleLogout);
    document.getElementById('predictions-history-btn').addEventListener('click', () => {
      document.getElementById('account-menu-dropdown').classList.add('hidden');
      openPredictionsModal();
    });
    checkForNewPredictionResults();
  } else {
    statusContainer.innerHTML = `
      <button class="btn btn-primary btn-small" id="login-open-btn" data-i18n="auth.login">${t('auth.login')}</button>
    `;
    document.getElementById('login-open-btn').addEventListener('click', () => openAuthModal('login'));
  }

  document.dispatchEvent(new CustomEvent('bfb:user-changed'));
}

// Cierra el menú de cuenta si se toca fuera de él.
document.addEventListener('click', (clickEvent) => {
  const accountMenu = document.getElementById('account-menu-dropdown');
  if (accountMenu && !accountMenu.classList.contains('hidden') && !clickEvent.target.closest('.account-menu')) {
    accountMenu.classList.add('hidden');
  }
});

async function refreshCurrentUser() {
  try {
    window.currentUser = await api.get('/auth/me');
  } catch (_) {
    window.currentUser = null;
  }
  renderUserStatus();
}

async function handleLogout() {
  await api.post('/auth/logout').catch(() => {});
  window.currentUser = null;
  renderUserStatus();
}

function openAuthModal(mode = 'login') {
  const modalBackdrop = document.getElementById('auth-modal-backdrop');
  modalBackdrop.classList.remove('hidden');
  setAuthMode(mode);
  document.getElementById('auth-error').textContent = '';
}

function closeAuthModal() {
  document.getElementById('auth-modal-backdrop').classList.add('hidden');
  document.getElementById('auth-form').reset();
}

function setAuthMode(authMode) {
  const authForm = document.getElementById('auth-form');
  authForm.dataset.mode = authMode;
  const isRegister = authMode === 'register';

  document.getElementById('auth-title').textContent = isRegister ? t('auth.register') : t('auth.login');
  document.getElementById('email-field').classList.toggle('hidden', !isRegister);
  document.getElementById('auth-submit-btn').textContent = isRegister ? t('auth.register') : t('auth.login');
  document.getElementById('auth-switch-text').textContent = isRegister ? t('auth.hasAccount') : t('auth.noAccount');
  document.getElementById('auth-switch-btn').textContent = isRegister ? t('auth.loginInstead') : t('auth.createOne');
}

async function handleAuthSubmit(submitEvent) {
  submitEvent.preventDefault();
  const authForm = submitEvent.target;
  const authMode = authForm.dataset.mode;
  const errorBanner = document.getElementById('auth-error');
  errorBanner.textContent = '';

  const username = document.getElementById('auth-username').value.trim();
  const password = document.getElementById('auth-password').value;
  const email = document.getElementById('auth-email').value.trim();

  try {
    if (authMode === 'register') {
      window.currentUser = await api.post('/auth/register', { username, email, password });
    } else {
      window.currentUser = await api.post('/auth/login', { username, password });
    }
    renderUserStatus();
    closeAuthModal();
  } catch (authError) {
    errorBanner.textContent = authError.message;
  }
}

function initAuth() {
  document.getElementById('auth-form').addEventListener('submit', handleAuthSubmit);
  document.getElementById('auth-modal-close').addEventListener('click', closeAuthModal);
  document.getElementById('auth-switch-btn').addEventListener('click', () => {
    const authForm = document.getElementById('auth-form');
    setAuthMode(authForm.dataset.mode === 'register' ? 'login' : 'register');
  });
  document.getElementById('auth-modal-backdrop').addEventListener('click', (clickEvent) => {
    if (clickEvent.target.id === 'auth-modal-backdrop') closeAuthModal();
  });
  refreshCurrentUser();
}
