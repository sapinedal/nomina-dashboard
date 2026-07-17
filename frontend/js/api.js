/**
 * api.js — Cliente HTTP centralizado para NóminaBoard.
 * Adjunta el token JWT en cada petición y maneja errores globales.
 */

const API_BASE = window.location.origin;

async function apiFetch(endpoint, options = {}) {
  const token = localStorage.getItem('token');
  const headers = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(options.headers || {}),
  };

  const res = await fetch(`${API_BASE}${endpoint}`, { ...options, headers });

  if (res.status === 401) {
    localStorage.removeItem('token');
    localStorage.removeItem('user');
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
  toast.innerHTML = `<i class="bi bi-${icons[type] || 'info-circle-fill'}"></i>${message}
    <button style="margin-left:auto;background:none;border:none;color:inherit;cursor:pointer;font-size:.9rem" onclick="this.closest('.toast').remove()">✕</button>`;
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

/** Cerrar sesión */
function logout() {
  localStorage.removeItem('token');
  localStorage.removeItem('user');
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
