/**
 * api.js — Cliente HTTP centralizado para NóminaBoard.
 * Adjunta el token JWT en cada petición y maneja errores globales.
 */

const API_BASE = window.location.origin;

// ── Sesión: access_token corto (15 min) + refresh_token (7 días) ──────
// El access_token se renueva solo, de dos formas:
//  1. Proactiva: un timer programado ~60s antes de que expire (scheduleTokenRefresh).
//     Se rearma en cada carga de página porque un timer de JS no sobrevive un reload.
//  2. Reactiva (red de seguridad): si igual llega un 401 -- ej. la pestaña
//     estuvo dormida y el timer nunca corrió -- apiFetch intenta refrescar
//     una vez antes de desloguear.
// refreshInFlight comparte una única promesa entre requests concurrentes:
// si el dashboard dispara 10 llamadas a la vez y todas reciben 401 juntas,
// las 10 esperan el MISMO refresh en vez de disparar 10 por separado.
const TOKEN_REFRESH_MARGIN_SECONDS = 60;
let refreshTimer = null;
let refreshInFlight = null;

function storeSession({ access_token, refresh_token, expires_in }) {
  localStorage.setItem('token', access_token);
  if (refresh_token) localStorage.setItem('refresh_token', refresh_token);
  localStorage.setItem('token_expires_at', String(Date.now() + expires_in * 1000));
  scheduleTokenRefresh();
}

function clearSession() {
  localStorage.removeItem('token');
  localStorage.removeItem('refresh_token');
  localStorage.removeItem('token_expires_at');
  localStorage.removeItem('user');
  if (refreshTimer) {
    clearTimeout(refreshTimer);
    refreshTimer = null;
  }
}

function scheduleTokenRefresh() {
  if (refreshTimer) clearTimeout(refreshTimer);
  const expiresAt = parseInt(localStorage.getItem('token_expires_at') || '0', 10);
  if (!expiresAt) return;
  const msUntilRefresh = Math.max(
    (expiresAt - Date.now()) - TOKEN_REFRESH_MARGIN_SECONDS * 1000,
    5000, // piso de 5s: evita refrescos en loop si el reloj del sistema está mal
  );
  refreshTimer = setTimeout(() => { refreshAccessToken().catch(() => {}); }, msUntilRefresh);
}

/** Canjea el refresh_token guardado por un access_token nuevo.
 *  Si falla (refresh_token vencido/inválido/ausente), limpia la sesión y
 *  redirige a login -- por eso los llamadores no necesitan manejar ese caso. */
function refreshAccessToken() {
  if (refreshInFlight) return refreshInFlight;

  const refreshToken = localStorage.getItem('refresh_token');
  if (!refreshToken) {
    clearSession();
    window.location.href = 'login.html';
    return Promise.reject(new Error('Sin refresh token'));
  }

  refreshInFlight = fetch(`${API_BASE}/api/auth/refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: refreshToken }),
  })
    .then(res => {
      if (!res.ok) throw new Error('refresh_failed');
      return res.json();
    })
    .then(data => {
      localStorage.setItem('token', data.access_token);
      localStorage.setItem('token_expires_at', String(Date.now() + data.expires_in * 1000));
      scheduleTokenRefresh();
      return data.access_token;
    })
    .catch(err => {
      clearSession();
      window.location.href = 'login.html';
      throw err;
    })
    .finally(() => { refreshInFlight = null; });

  return refreshInFlight;
}

// Un timer de JS no sobrevive un reload de página: si ya hay sesión al
// cargar este script, rearmarlo con el tiempo restante real.
if (localStorage.getItem('token') && localStorage.getItem('refresh_token')) {
  scheduleTokenRefresh();
}

async function apiFetch(endpoint, options = {}) {
  const token = localStorage.getItem('token');
  const headers = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(options.headers || {}),
  };

  let res = await fetch(`${API_BASE}${endpoint}`, { ...options, headers });

  if (res.status === 401 && localStorage.getItem('refresh_token')) {
    try {
      const newToken = await refreshAccessToken();
      res = await fetch(`${API_BASE}${endpoint}`, {
        ...options,
        headers: { ...headers, Authorization: `Bearer ${newToken}` },
      });
    } catch {
      return; // refreshAccessToken ya limpió la sesión y redirigió a login
    }
  }

  if (res.status === 401) {
    clearSession();
    window.location.href = 'login.html';
    return;
  }

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: `Error HTTP ${res.status}` }));
    throw new Error(err.detail || `Error ${res.status}`);
  }

  // 204 No Content
  if (res.status === 204) return null;
  return res.json();
}

const API = {
  // ── Auth
  login: (username, password) => {
    const body = new URLSearchParams({ username, password });
    return fetch(`${API_BASE}/api/auth/token`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: body.toString(),
    }).then(r => r.ok ? r.json() : r.json().then(e => Promise.reject(new Error(e.detail))));
  },

  // ── Dashboard
  getKPIs:           (params = {}) => apiFetch('/api/dashboard/kpis?' + new URLSearchParams(clean(params))),
  getChartTipo:      (params = {}) => apiFetch('/api/dashboard/charts/novedades-por-tipo?' + new URLSearchParams(clean(params))),
  getChartArea:      (params = {}) => apiFetch('/api/dashboard/charts/novedades-por-area?' + new URLSearchParams(clean(params))),
  getChartTrend:     (params = {}) => apiFetch('/api/dashboard/charts/tendencia-mensual?' + new URLSearchParams(clean(params))),
  getChartValor:          (params = {}) => apiFetch('/api/dashboard/charts/valor-por-area?' + new URLSearchParams(clean(params))),
  getChartValorCategoria: (params = {}) => apiFetch('/api/dashboard/charts/valor-por-categoria?' + new URLSearchParams(clean(params))),
  getTable:          (params = {}) => apiFetch('/api/dashboard/table?' + new URLSearchParams(clean(params))),
  getFilterOpts:     (panel = null, periodo = null) => apiFetch('/api/dashboard/filter-options?' + new URLSearchParams(clean({ panel, periodo }))),
  getAlerts:         (params = {}) => apiFetch('/api/dashboard/alerts?' + new URLSearchParams(clean(params))),
  getAlertsDetalle:  (params = {}) => apiFetch('/api/dashboard/alerts/detalle?' + new URLSearchParams(clean(params))),
  getPanelAusent:    (params = {}) => apiFetch('/api/dashboard/panel/ausentismo?' + new URLSearchParams(clean(params))),
  getAusentismoEmpleados: (params = {}) => apiFetch('/api/dashboard/ausentismo/empleados?' + new URLSearchParams(clean(params))),
  getPanelHorasExt:  (params = {}) => apiFetch('/api/dashboard/panel/horas-extras?' + new URLSearchParams(clean(params))),
  getEmpleados:      (params = {}) => apiFetch('/api/dashboard/empleados?'      + new URLSearchParams(clean(params))),
  getResumenPorArea: (params = {}) => apiFetch('/api/dashboard/resumen-por-area?' + new URLSearchParams(clean(params))),

  // ── Ejecuciones
  executions:    '/api/execution/history',
  etlTrigger:    '/api/execution/trigger',
  getHistory:    (limit = 20)  => apiFetch(`/api/execution/history?limit=${limit}`),
  getExecution:  (id)          => apiFetch(`/api/execution/${id}`),
  triggerETL:    ()            => apiFetch('/api/execution/trigger', { method: 'POST' }),
  triggerTrazalo:()            => apiFetch('/api/execution/trigger-trazalo', { method: 'POST' }),

  // ── Usuarios
  users:         '/api/users/',
  getUsers:      ()            => apiFetch('/api/users/'),
  createUser:    (data)        => apiFetch('/api/users/', { method: 'POST', body: JSON.stringify(data) }),
  updateUser:    (id, data)    => apiFetch(`/api/users/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteUser:    (id)          => apiFetch(`/api/users/${id}`, { method: 'DELETE' }),

  // ── Exportación
  exportExcel:   (params = {}) => `${API_BASE}/api/export/excel?` + new URLSearchParams(clean(params)),
  exportPDF:     (params = {}) => `${API_BASE}/api/export/pdf?`   + new URLSearchParams(clean(params)),
};

/** Eliminar claves con valores nulos/vacíos antes de serializar params */
function clean(obj) {
  return Object.fromEntries(
    Object.entries(obj).filter(([, v]) => v !== null && v !== undefined && v !== '')
  );
}

/** Mostrar toast de notificación */
function showToast(message, type = 'success') {
  let container = document.getElementById('toast-container');
  if (!container) {
    container = document.createElement('div');
    container.className = 'toast-container';
    container.id = 'toast-container';
    document.body.appendChild(container);
  }
  const icons = { success: 'check-circle-fill', danger: 'exclamation-triangle-fill', info: 'info-circle-fill', warning: 'exclamation-circle-fill' };
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  // El icono y el botón son estructura fija; el `message` puede venir de un
  // error de la API (que a su vez puede reflejar datos de origen), así que se
  // inserta como nodo de texto (textContent) — nunca interpolado en innerHTML —
  // para que un mensaje con HTML no se ejecute (XSS). Autónomo: no depende de
  // escape-html.js, que no todas las páginas cargan.
  toast.innerHTML = `<i class="bi bi-${icons[type] || 'info-circle-fill'}"></i><span class="toast-msg"></span>` +
    `<button style="margin-left:auto;background:none;border:none;color:inherit;cursor:pointer;font-size:.9rem" onclick="this.closest('.toast').remove()">✕</button>`;
  toast.querySelector('.toast-msg').textContent = message;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 5000);
}

/** Obtener usuario actual del localStorage */
function getCurrentUser() {
  try { return JSON.parse(localStorage.getItem('user') || 'null'); }
  catch { return null; }
}

/** Verificar sesión, redirigir si no hay token */
function requireAuth() {
  if (!localStorage.getItem('token')) window.location.href = 'login.html';
}

/** Cerrar sesión: revoca el token en el servidor (best-effort) y limpia la
 *  sesión local siempre, incluso si la llamada al backend falla por red --
 *  el usuario no debe quedar atrapado sin poder desloguearse localmente
 *  solo porque no hay conexión. */
async function logout() {
  const token = localStorage.getItem('token');
  const refreshToken = localStorage.getItem('refresh_token');
  if (token) {
    try {
      await fetch(`${API_BASE}/api/auth/logout`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ refresh_token: refreshToken || undefined }),
      });
    } catch {
      // Sin red: igual limpiamos la sesión local. El access_token expira
      // solo en <=15 min; no vale la pena bloquear el logout local por esto.
    }
  }
  clearSession();
  window.location.href = 'login.html';
}

/** Formatear número como moneda colombiana */
function formatCOP(value) {
  if (value == null) return '—';
  return new Intl.NumberFormat('es-CO', { style: 'currency', currency: 'COP', maximumFractionDigits: 0 }).format(value);
}

/** Formatear número con separadores de miles */
function formatNumber(value) {
  if (value == null) return '—';
  return new Intl.NumberFormat('es-CO').format(value);
}

/** Formatear período YYYY-MM → "Mes Año" en español */
function formatPeriodo(p) {
  if (!p) return '—';
  const m = String(p).match(/^(\d{4})-(\d{2})$/);
  if (!m) return p;
  const meses = ['Enero','Febrero','Marzo','Abril','Mayo','Junio',
                 'Julio','Agosto','Septiembre','Octubre','Noviembre','Diciembre'];
  const mes = meses[parseInt(m[2], 10) - 1];
  return mes ? `${mes} ${m[1]}` : p;
}

/** Formatear fecha ISO a dd/mm/yyyy (acepta date, datetime y timestamp) */
function formatDate(value) {
  if (!value) return '—';
  // Si ya tiene componente de hora, no añadir T00:00:00
  const s = String(value);
  const d = s.includes('T') || s.includes(' ') ? new Date(s) : new Date(s + 'T00:00:00');
  if (isNaN(d.getTime())) return value;
  return d.toLocaleDateString('es-CO', { day: '2-digit', month: '2-digit', year: 'numeric' });
}
