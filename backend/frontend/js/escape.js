/**
 * escape.js — helpers XSS mínimos, sin dependencias.
 *
 * - esc(value): escapa &<>"' para interpolar texto en innerHTML.
 * - safeUrl(url): allowlist de URLs para href/src. Solo admite http:, https:
 *   y rutas relativas (/... o sin esquema). Cualquier otro esquema
 *   (javascript:, data:, vbscript:, file:) devuelve '#'.
 * - safeImg(url): igual que safeUrl pero admite además data:image/* (logos
 *   embebidos). El resto de data: se rechaza.
 */

function esc(value) {
  if (value === null || value === undefined) return '';
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function _isHttpUrl(parsedUrl) {
  return parsedUrl.protocol === 'http:' || parsedUrl.protocol === 'https:';
}

function safeUrl(value) {
  if (value === null || value === undefined) return '#';
  const rawUrl = String(value).trim();
  if (!rawUrl || rawUrl.startsWith('#')) return rawUrl || '#';
  // Rutas relativas ("/x", "x/y", "./x", "?q=1") sin esquema: seguras.
  if (rawUrl.startsWith('/') || rawUrl.startsWith('./') || rawUrl.startsWith('../') || rawUrl.startsWith('?')) return rawUrl;
  try {
    const parsedUrl = new URL(rawUrl, window.location.origin);
    // Si el input no traía esquema, URL lo resolvió contra el origen:
    // solo se acepta si quedó en el mismo origen (relativa real).
    const hasScheme = /^[a-zA-Z][a-zA-Z0-9+.-]*:/.test(rawUrl);
    if (!hasScheme) {
      return parsedUrl.origin === window.location.origin ? rawUrl : '#';
    }
    return _isHttpUrl(parsedUrl) ? parsedUrl.href : '#';
  } catch (_) {
    return '#';
  }
}

function safeImg(value) {
  if (value === null || value === undefined) return '';
  const rawUrl = String(value).trim();
  if (!rawUrl) return '';
  if (rawUrl.startsWith('data:image/')) {
    // data:image/png;base64,... — se acepta solo si no contiene < o ".
    if (/[<"]/.test(rawUrl)) return '';
    return rawUrl;
  }
  const sanitizedUrl = safeUrl(rawUrl);
  return sanitizedUrl === '#' ? '' : sanitizedUrl;
}

// Exposición global (scripts clásicos, sin bundler).
window.esc = esc;
window.safeUrl = safeUrl;
window.safeImg = safeImg;
