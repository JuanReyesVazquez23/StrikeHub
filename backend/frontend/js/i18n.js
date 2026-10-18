/**
 * Internacionalización simple basada en diccionarios JSON (es/en).
 * El idioma elegido se guarda en localStorage (dato no sensible: solo una
 * preferencia de interfaz) y, si el usuario tiene sesión iniciada, también
 * se sincroniza con su perfil en el backend.
 */
const i18nState = {
  lang: localStorage.getItem('bfb_lang') || 'es',
  messages: {},
};

const I18N_VERSION = '20261021';

async function loadDictionary(lang) {
  const localeResponse = await fetch(`i18n/${lang}.json?v=${I18N_VERSION}`);
  return localeResponse.json();
}

function t(key) {
  const keySegments = key.split('.');
  let currentEntry = i18nState.messages;
  for (const segment of keySegments) {
    currentEntry = currentEntry?.[segment];
  }
  return currentEntry ?? key;
}

function applyTranslations() {
  document.querySelectorAll('[data-i18n]').forEach((element) => {
    const translatedText = t(element.dataset.i18n);
    // Si una versión anterior del diccionario sigue en caché, conserva el
    // texto escrito en HTML en lugar de mostrar la clave técnica (ej. header.kicker).
    if (translatedText !== element.dataset.i18n) element.textContent = translatedText;
  });
  document.querySelectorAll('[data-i18n-placeholder]').forEach((element) => {
    const translatedText = t(element.dataset.i18nPlaceholder);
    if (translatedText !== element.dataset.i18nPlaceholder) element.placeholder = translatedText;
  });
  document.documentElement.lang = i18nState.lang;
}

async function setLanguage(lang) {
  i18nState.lang = lang;
  localStorage.setItem('bfb_lang', lang);
  i18nState.messages = await loadDictionary(lang);
  applyTranslations();

  // Si hay sesión activa, guarda la preferencia en el backend también.
  if (window.currentUser) {
    api.patch('/auth/me/language', { preferred_language: lang }).catch(() => {});
  }

  document.dispatchEvent(new CustomEvent('bfb:language-changed', { detail: { lang } }));
}

async function initI18n() {
  i18nState.messages = await loadDictionary(i18nState.lang);
  applyTranslations();
  const languageSelector = document.getElementById('lang-select');
  if (languageSelector) {
    languageSelector.value = i18nState.lang;
    languageSelector.addEventListener('change', (event) => setLanguage(event.target.value));
  }
}
