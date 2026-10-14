/**
 * Cliente HTTP hacia el backend de StrikeHub.
 *
 * - Usa `credentials: 'include'` para enviar/recibir la cookie httpOnly de
 *   sesión (ver backend/app/api/routes/auth.py). El token JWT nunca se toca
 *   ni se guarda desde JavaScript, precisamente para reducir el riesgo de
 *   robo de sesión por XSS.
 * - BASE_URL apunta al mismo origen por defecto (backend sirviendo también
 *   el frontend). Si despliegas el frontend en otro dominio, cambia esto.
 */
const API_BASE_URL = `${window.location.origin}/api/v1`;

class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function apiRequest(path, { method = 'GET', body = null } = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method,
    credentials: 'include',
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
  });

  if (response.status === 204) return null;

  let responseBody = null;
  try {
    responseBody = await response.json();
  } catch (_) {
    responseBody = null;
  }

  if (!response.ok) {
    // FastAPI devuelve detail como string o como array de errores de
    // validación ({loc, msg}). Se normaliza a string para que el frontend
    // nunca interpole objetos ([object Object]) en el DOM.
    let message = 'Error de comunicación con el servidor.';
    const detail = responseBody && responseBody.detail;
    if (typeof detail === 'string' && detail) {
      message = detail;
    } else if (Array.isArray(detail) && detail.length) {
      message = detail
        .map((validationError) => (typeof validationError === 'string' ? validationError : validationError && validationError.msg ? String(validationError.msg) : ''))
        .filter(Boolean)
        .join(' · ') || message;
    }
    throw new ApiError(message, response.status);
  }

  return responseBody;
}

const api = {
  get: (path) => apiRequest(path),
  post: (path, body) => apiRequest(path, { method: 'POST', body }),
  patch: (path, body) => apiRequest(path, { method: 'PATCH', body }),
  delete: (path) => apiRequest(path, { method: 'DELETE' }),
};
