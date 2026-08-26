/**
 * api.js — Cliente HTTP centralizado para NóminaBoard.
 * Sesión vía cookies HttpOnly (credentials: 'include'). No guarda JWT en localStorage.
 */

const API_BASE = window.location.origin;

// ── Sesión: access cookie corta + refresh cookie (7 días) ─────────────
// El access_token vive en cookie HttpOnly; JS solo guarda expires_at para
// programar el refresh proactivo. Refresh también va por cookie.
const TOKEN_REFRESH_MARGIN_SECONDS = 60;
let refreshTimer = null;
let refreshInFlight = null;

/** Normaliza errores FastAPI (string | {detail} | detail[]) — DEF-0005 */
function formatApiError(payload, fallback = 'Error inesperado') {
  if (payload == null) return fallback;
  if (typeof payload === 'string') return payload;
  const detail = payload.detail !== undefined ? payload.detail : payload;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d) => {
        if (typeof d === 'string') return d;
        if (d && typeof d.msg === 'string') return d.msg;
        if (d && typeof d.message === 'string') return d.message;
        return null;
      })
      .filter(Boolean)
      .join('; ') || fallback;
  }
  if (detail && typeof detail === 'object' && typeof detail.msg === 'string') return detail.msg;
  return fallback;
}

function storeSession({ expires_in, user } = {}) {
  // Solo metadatos no sensibles en sessionStorage (DEF-0003).
  if (expires_in != null) {
    sessionStorage.setItem('token_expires_at', String(Date.now() + expires_in * 1000));
  }
  if (user) {
    sessionStorage.setItem('user', JSON.stringify(user));
  }
  // Limpia JWT legacy en localStorage
  localStorage.removeItem('token');
  localStorage.removeItem('refresh_token');
  localStorage.removeItem('token_expires_at');
  localStorage.removeItem('user');
  scheduleTokenRefresh();
}

/** El login es la unica pagina que NO debe redirigirse a si misma en un 401:
 *  hacerlo la recarga en bucle sin que el usuario llegue a escribir nada. */
function isLoginPage() {
  return /(^|[/])login[.]html$/.test(window.location.pathname);
}

function clearSession() {
  sessionStorage.removeItem('token_expires_at');
  sessionStorage.removeItem('user');
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
  const expiresAt = parseInt(sessionStorage.getItem('token_expires_at') || '0', 10);
  if (!expiresAt) return;
  const msUntilRefresh = Math.max(
    (expiresAt - Date.now()) - TOKEN_REFRESH_MARGIN_SECONDS * 1000,
    5000,
  );
  refreshTimer = setTimeout(() => { refreshAccessToken().catch(() => {}); }, msUntilRefresh);
}

/** Renueva access vía cookie refresh HttpOnly (body vacío). */
function refreshAccessToken() {
  if (refreshInFlight) return refreshInFlight;

  refreshInFlight = fetch(`${API_BASE}/api/auth/refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: '{}',
    credentials: 'include',
  })
    .then(async (res) => {
      if (!res.ok) throw new Error('refresh_failed');
      return res.json();
    })
    .then((data) => {
      storeSession({ expires_in: data.expires_in });
      return data.access_token;
    })
    .catch((err) => {
      clearSession();
      if (!isLoginPage()) {
        window.location.href = 'login.html';
      }
      throw err;
    })
    .finally(() => { refreshInFlight = null; });

  return refreshInFlight;
}

if (sessionStorage.getItem('token_expires_at')) {
  scheduleTokenRefresh();
}

async function apiFetch(endpoint, options = {}) {
  const headers = {
    ...(options.body && !(options.body instanceof FormData)
      ? { 'Content-Type': 'application/json' }
      : {}),
    ...(options.headers || {}),
  };

  let res = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers,
    credentials: 'include',
  });

  if (res.status === 401 && sessionStorage.getItem('token_expires_at')) {
    try {
      await refreshAccessToken();
      res = await fetch(`${API_BASE}${endpoint}`, {
        ...options,
        headers,
        credentials: 'include',
      });
    } catch (err) {
      // Mismo motivo que abajo: no resolver como si hubiera ido bien.
      throw err;
    }
  }

  if (res.status === 401) {
    clearSession();
    // Devolver aqui (en vez de lanzar) resolvia la promesa con undefined, asi
    // que los `.then()` lo trataban como exito. En login.html eso disparaba
    // `location.href = 'dashboard.html'`, el dashboard volvia a dar 401 y
    // rebotaba al login: bucle infinito de recargas.
    if (!isLoginPage()) {
      window.location.href = 'login.html';
    }
    throw new Error('Sesion expirada');
  }

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: `Error HTTP ${res.status}` }));
    throw new Error(formatApiError(err, `Error ${res.status}`));
  }

  if (res.status === 204) return null;
  return res.json();
}

const API = {
  login: (username, password) => {
    const body = new URLSearchParams({ username, password });
    return fetch(`${API_BASE}/api/auth/token`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: body.toString(),
      credentials: 'include',
    }).then(async (r) => {
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(formatApiError(data, 'Usuario o contraseña incorrectos'));
      return data;
    });
  },
  me: () => apiFetch('/api/auth/me'),

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
  getDetalleHorasExtTipo: (params = {}) => apiFetch('/api/dashboard/panel/horas-extras/detalle?' + new URLSearchParams(clean(params))),
  getEmpleados:      (params = {}) => apiFetch('/api/dashboard/empleados?'      + new URLSearchParams(clean(params))),
  getResumenPorArea: (params = {}) => apiFetch('/api/dashboard/resumen-por-area?' + new URLSearchParams(clean(params))),

  executions:    '/api/execution/history',
  etlTrigger:    '/api/execution/trigger',
  getHistory:    (limit = 20)  => apiFetch(`/api/execution/history?limit=${limit}`),
  getExecution:  (id)          => apiFetch(`/api/execution/${id}`),
  triggerETL:    ()            => apiFetch('/api/execution/trigger', { method: 'POST' }),
  triggerTrazalo:()            => apiFetch('/api/execution/trigger-trazalo', { method: 'POST' }),

  users:         '/api/users/',
  getUsers:      ()            => apiFetch('/api/users/'),
  createUser:    (data)        => apiFetch('/api/users/', { method: 'POST', body: JSON.stringify(data) }),
  updateUser:    (id, data)    => apiFetch(`/api/users/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteUser:    (id)          => apiFetch(`/api/users/${id}`, { method: 'DELETE' }),

  downloadExcel: (params = {}) => downloadFile('/api/export/excel?' + new URLSearchParams(clean(params))),
  downloadPDF:   (params = {}) => downloadFile('/api/export/pdf?'   + new URLSearchParams(clean(params))),
  downloadReporteNomina: (params = {}) => downloadFile('/api/export/nomina?' + new URLSearchParams(clean(params))),
};

/** Permisos por perfil. Espejo de backend/app/services/permissions.py, usado
 *  solo como respaldo: la fuente real es `user.permissions` que llega en
 *  /api/auth/me. Si ambos difieren manda el backend, que es quien bloquea. */
const ROLE_PERMISSIONS = {
  admin:    ['empleados_periodo', 'export_excel', 'export_pdf', 'usuarios', 'etl'],
  analyst:  ['empleados_periodo', 'export_excel', 'export_pdf'],
  readonly: [],
};

const PERMISSION_LABELS = {
  empleados_periodo: 'Ver empleados por período',
  export_excel:      'Exportar a Excel',
  export_pdf:        'Exportar a PDF',
  usuarios:          'Administrar usuarios',
  etl:               'Ejecutar carga ETL / Trazalo',
};

function permissionsForRole(role) {
  return ROLE_PERMISSIONS[role] || [];
}

function hasPermission(code) {
  const user = getCurrentUser();
  if (!user) return false;
  const perms = Array.isArray(user.permissions) ? user.permissions : permissionsForRole(user.role);
  return perms.includes(code);
}

/** Descarga por fetch en vez de <a href> para poder leer el error: si el
 *  backend responde 403 por permisos, un enlace directo abriría una pestaña
 *  con JSON crudo en lugar de avisar en la interfaz. */
async function downloadFile(endpoint) {
  let res = await fetch(`${API_BASE}${endpoint}`, { credentials: 'include' });

  if (res.status === 401 && sessionStorage.getItem('token_expires_at')) {
    try {
      await refreshAccessToken();
      res = await fetch(`${API_BASE}${endpoint}`, { credentials: 'include' });
    } catch (err) {
      // Mismo motivo que abajo: no resolver como si hubiera ido bien.
      throw err;
    }
  }

  if (res.status === 401) {
    clearSession();
    // Devolver aqui (en vez de lanzar) resolvia la promesa con undefined, asi
    // que los `.then()` lo trataban como exito. En login.html eso disparaba
    // `location.href = 'dashboard.html'`, el dashboard volvia a dar 401 y
    // rebotaba al login: bucle infinito de recargas.
    if (!isLoginPage()) {
      window.location.href = 'login.html';
    }
    throw new Error('Sesion expirada');
  }

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: `Error HTTP ${res.status}` }));
    throw new Error(formatApiError(err, `Error ${res.status}`));
  }

  const match = (res.headers.get('Content-Disposition') || '').match(/filename="?([^";]+)"?/i);
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement('a');
  a.href = url;
  a.download = match ? match[1] : 'descarga';
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** Descarta filtros vacios y serializa los que son lista como parametros
 *  repetidos (?area=NOMINA&area=SST), que es lo que espera FastAPI para un
 *  Query(List[str]).
 *
 *  Devuelve URLSearchParams a proposito: `new URLSearchParams(clean(p))` usa
 *  el constructor de copia, asi que todas las llamadas existentes siguen
 *  funcionando sin tocarlas. Pasar un objeto plano con un array habria
 *  producido "area=NOMINA,SST", una sola area con una coma dentro. */
function clean(obj) {
  const vacio = (v) => v === null || v === undefined || v === '';
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(obj)) {
    if (Array.isArray(v)) {
      v.filter((item) => !vacio(item)).forEach((item) => params.append(k, item));
    } else if (!vacio(v)) {
      params.append(k, v);
    }
  }
  return params;
}

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
  toast.innerHTML = `<i class="bi bi-${icons[type] || 'info-circle-fill'}"></i><span class="toast-msg"></span>` +
    `<button style="margin-left:auto;background:none;border:none;color:inherit;cursor:pointer;font-size:.9rem" onclick="this.closest('.toast').remove()">✕</button>`;
  toast.querySelector('.toast-msg').textContent = message;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 5000);
}

function getCurrentUser() {
  try { return JSON.parse(sessionStorage.getItem('user') || 'null'); }
  catch { return null; }
}

/** Verifica sesión vía cookie HttpOnly (/api/auth/me). */
async function requireAuth() {
  try {
    const user = await API.me();
    sessionStorage.setItem('user', JSON.stringify(user));
    return user;
  } catch {
    clearSession();
    window.location.href = 'login.html';
    return null;
  }
}

async function logout() {
  try {
    await fetch(`${API_BASE}/api/auth/logout`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}',
      credentials: 'include',
    });
  } catch {
    // Sin red: igual limpiamos metadatos locales.
  }
  clearSession();
  window.location.href = 'login.html';
}

function formatCOP(value) {
  if (value == null) return '—';
  return new Intl.NumberFormat('es-CO', { style: 'currency', currency: 'COP', maximumFractionDigits: 0 }).format(value);
}

function formatNumber(value) {
  if (value == null) return '—';
  return new Intl.NumberFormat('es-CO').format(value);
}

function formatPeriodo(p) {
  if (!p) return '—';
  const m = String(p).match(/^(\d{4})-(\d{2})$/);
  if (!m) return p;
  const meses = ['Enero','Febrero','Marzo','Abril','Mayo','Junio',
                 'Julio','Agosto','Septiembre','Octubre','Noviembre','Diciembre'];
  const mes = meses[parseInt(m[2], 10) - 1];
  return mes ? `${mes} ${m[1]}` : p;
}

function formatDate(value) {
  if (!value) return '—';
  const s = String(value);
  const d = s.includes('T') || s.includes(' ') ? new Date(s) : new Date(s + 'T00:00:00');
  if (isNaN(d.getTime())) return value;
  return d.toLocaleDateString('es-CO', { day: '2-digit', month: '2-digit', year: 'numeric' });
}
