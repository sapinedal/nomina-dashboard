/**
 * dashboard.js — Lógica del tablero NóminaBoard 2.0
 */

let currentFilters = {};
let tableState = { page: 1, pageSize: 50, sortBy: 'id', sortDir: 'desc', total: 0 };
let activePanel = 'ejecutivo';

// ── Inicialización ────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', async () => {
  requireAuth();
  initUserUI();
  initDarkMode();
  initPanelTabs();
  initFilterListeners();
  initTableSorting();
  await loadFilterOptions();
  updateFilterBar('ejecutivo');
  await loadPanel('ejecutivo');
});

function initUserUI() {
  const user = getCurrentUser();
  if (!user) return;

  const nameEl = document.getElementById('user-name');
  const roleEl = document.getElementById('user-role');
  if (nameEl) nameEl.textContent = user.full_name || user.username;
  if (roleEl) {
    const labels = { admin: 'Admin', analyst: 'Analista', readonly: 'Consulta' };
    roleEl.textContent = labels[user.role] || user.role;
    roleEl.className = `role-badge role-${user.role}`;
  }

  if (user.role === 'admin') {
    const navAdmin = document.getElementById('nav-admin');
    if (navAdmin) navAdmin.style.display = 'flex';
  }
  if (user.role === 'admin' || user.role === 'analyst') {
    document.querySelectorAll('.analyst-only').forEach(el => { el.style.display = 'flex'; });
  }
}

// ── Dark mode ─────────────────────────────────────────────────

function initDarkMode() {
  const saved = localStorage.getItem('darkMode');
  if (saved === '1') applyDark(true);

  document.getElementById('btn-dark-mode')?.addEventListener('click', () => {
    const isDark = document.body.classList.contains('dark-mode');
    applyDark(!isDark);
    localStorage.setItem('darkMode', isDark ? '0' : '1');
  });
}

function applyDark(on) {
  document.body.classList.toggle('dark-mode', on);
  const btn = document.getElementById('btn-dark-mode');
  if (btn) btn.innerHTML = on
    ? '<i class="bi bi-sun"></i>'
    : '<i class="bi bi-moon-stars"></i>';
}

// ── Panel tabs ────────────────────────────────────────────────

function initPanelTabs() {
  document.querySelectorAll('.panel-tab').forEach(btn => {
    btn.addEventListener('click', () => {
      const panel = btn.dataset.panel;
      switchPanel(panel);
    });
  });
}

async function switchPanel(panelName) {
  document.querySelectorAll('.panel-tab').forEach(b =>
    b.classList.toggle('active', b.dataset.panel === panelName)
  );
  document.querySelectorAll('.panel-section').forEach(s => s.classList.remove('active'));
  const section = document.getElementById(`panel-${panelName}`);
  if (section) section.classList.add('active');

  activePanel = panelName;
  updateFilterBar(panelName);
  await refreshAreaSedeOptions(panelName);
  await loadPanel(panelName);
}

// ── Área/Sede: opciones acotadas por panel (ausentismo / horas-extras) ──

async function refreshAreaSedeOptions(panelName) {
  const panelParam = (panelName === 'ausentismo' || panelName === 'horas-extras') ? panelName : null;
  // Para ausentismo/horas-extras, acotar también al período seleccionado.
  const periodoParam = panelParam
    ? (document.getElementById('filter-periodo')?.value || null)
    : null;
  try {
    const opts = await API.getFilterOpts(panelParam, periodoParam);
    const areas = opts.areas || [];
    const sedes = opts.sedes || [];

    populateSelect('filter-area', areas);
    populateSelect('filter-sede', sedes);

    const areaSel = document.getElementById('filter-area');
    if (areaSel) {
      if (currentFilters.area && !areas.includes(currentFilters.area)) {
        areaSel.value = '';
        currentFilters.area = null;
      } else {
        areaSel.value = currentFilters.area || '';
      }
    }

    const sedeSel = document.getElementById('filter-sede');
    if (sedeSel) {
      if (currentFilters.sede && !sedes.includes(currentFilters.sede)) {
        sedeSel.value = '';
        currentFilters.sede = null;
      } else {
        sedeSel.value = currentFilters.sede || '';
      }
    }
  } catch (e) {
    console.warn('No se pudieron acotar área/sede para el panel:', e.message);
  }
}

// ── Filtros dinámicos por panel ───────────────────────────────

const PANEL_FILTER_CFG = {
  'ejecutivo':    { label: 'Ejecutivo',           color: 'var(--primary)' },
  'operativo':    { label: 'Operativo',           color: '#e67e22' },
  'ausentismo':   { label: 'Ausentismo',          color: '#27ae60' },
  'horas-extras': { label: 'H. Extras & Recargos', color: '#8e44ad' },
  'detalle':      { label: 'Detalle',             color: '#2980b9' },
};

function updateFilterBar(panelName) {
  const ctx = document.getElementById('filter-panel-ctx');
  if (ctx) {
    const cfg = PANEL_FILTER_CFG[panelName] || {};
    ctx.textContent = cfg.label || panelName;
    ctx.style.background = cfg.color || 'var(--primary)';
  }
  document.querySelectorAll('[data-panels]').forEach(el => {
    const visible = el.dataset.panels.split(',').includes(panelName);
    el.style.display = visible ? '' : 'none';
  });
}

async function loadPanel(panelName) {
  switch (panelName) {
    case 'ejecutivo':
      await Promise.all([loadKPIs(), loadCharts(), loadResumenPorArea(), loadEmpleadosLista()]);
      break;
    case 'operativo':
      await loadPanelOperativo();
      break;
    case 'ausentismo':
      await loadPanelAusentismo();
      break;
    case 'horas-extras':
      await loadPanelHorasExtras();
      break;
    case 'detalle':
      tableState.page = 1;
      await loadTable();
      break;
  }
}

// ── Opciones de filtro ────────────────────────────────────────

async function loadFilterOptions() {
  try {
    const opts = await API.getFilterOpts('ejecutivo');
    populateSelect('filter-area',    opts.areas         || []);
    populateSelect('filter-sede',    opts.sedes         || []);
    populateSelect('filter-tipo',    opts.tipos_novedad || []);
    populateSelect('filter-periodo', opts.periodos      || []);
  } catch (e) {
    console.warn('No se pudieron cargar opciones de filtro:', e.message);
  }
}

function populateSelect(id, items) {
  const sel = document.getElementById(id);
  if (!sel) return;
  const placeholder = sel.querySelector('option[value=""]');
  sel.innerHTML = '';
  if (placeholder) sel.appendChild(placeholder);
  items.forEach(v => {
    const opt = document.createElement('option');
    opt.value = opt.textContent = v;
    sel.appendChild(opt);
  });
}

// ── Listeners de filtros ──────────────────────────────────────

function initFilterListeners() {
  document.getElementById('btn-apply-filters')?.addEventListener('click', applyFilters);
  document.getElementById('btn-clear-filters')?.addEventListener('click', clearFilters);
  document.getElementById('btn-refresh')?.addEventListener('click', () => loadPanel(activePanel));
  // Auto-aplicar al cambiar dropdowns de selección única (área, sede, tipo)
  ['filter-area', 'filter-sede', 'filter-tipo'].forEach(id => {
    document.getElementById(id)?.addEventListener('change', applyFilters);
  });
  // Al cambiar el período, en ausentismo/horas-extras se debe reacotar
  // Área/Sede a ese mes antes de recargar el panel.
  document.getElementById('filter-periodo')?.addEventListener('change', async () => {
    currentFilters = getFiltersFromForm();
    if (activePanel === 'ausentismo' || activePanel === 'horas-extras') {
      await refreshAreaSedeOptions(activePanel);
      currentFilters = getFiltersFromForm();
    }
    tableState.page = 1;
    await loadPanel(activePanel);
  });
}

function getFiltersFromForm() {
  return {
    fecha_inicio: document.getElementById('filter-fecha-inicio')?.value || null,
    fecha_fin:    document.getElementById('filter-fecha-fin')?.value    || null,
    area:         document.getElementById('filter-area')?.value         || null,
    sede:         document.getElementById('filter-sede')?.value         || null,
    tipo_novedad: document.getElementById('filter-tipo')?.value         || null,
    periodo:      document.getElementById('filter-periodo')?.value      || null,
    cedula:       document.getElementById('filter-cedula')?.value       || null,
    solo_activos: document.getElementById('filter-solo-activos')?.checked || false,
  };
}

async function applyFilters() {
  currentFilters = getFiltersFromForm();
  tableState.page = 1;
  await loadPanel(activePanel);
}

async function clearFilters() {
  ['filter-fecha-inicio','filter-fecha-fin','filter-area','filter-sede',
   'filter-tipo','filter-periodo','filter-cedula']
    .forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
  const toggleActivos = document.getElementById('filter-solo-activos');
  if (toggleActivos) toggleActivos.checked = false;
  currentFilters = {};
  tableState.page = 1;
  await loadPanel(activePanel);
}

// ── KPIs ──────────────────────────────────────────────────────

async function loadKPIs() {
  try {
    const kpis = await API.getKPIs({ ...currentFilters, tipo_novedad: null });
    setText('kpi-total',     formatNumber(kpis.total_novedades));
    setText('kpi-empleados', formatNumber(kpis.total_empleados));
    setText('kpi-areas',     formatNumber(kpis.total_areas));
    setText('kpi-tipos',     formatNumber(kpis.total_tipos_novedad));
    setText('kpi-valor',     formatCOP(kpis.valor_calculado ?? kpis.valor_total));
    setText('kpi-dias',      kpis.promedio_dias?.toFixed(1) ?? '—');

    // KPIs adicionales
    setText('kpi-total-he',  kpis.total_horas_extras != null ? `${formatNumber(kpis.total_horas_extras)} h` : '—');
    setText('kpi-total-aus', kpis.total_dias_ausencia != null ? `${formatNumber(kpis.total_dias_ausencia)} d` : '—');
    setText('kpi-he-limite', kpis.empleados_he_limite != null ? formatNumber(kpis.empleados_he_limite) : '—');
    setText('kpi-valor-he',  kpis.valor_horas_extras != null ? formatCOP(kpis.valor_horas_extras) : '—');
    setText('kpi-valor-aus', kpis.valor_ausencias    != null ? formatCOP(kpis.valor_ausencias)    : '—');

    // Empleados sin salario real registrado (excluidos de los valores monetarios)
    if (kpis.empleados_sin_salario) {
      const nota = `⚠ ${formatNumber(kpis.empleados_sin_salario)} empleados sin salario registrado (excluidos)`;
      setText('kpi-valor-sub', nota);
      setText('kpi-valor-he-sub', nota);
      setText('kpi-valor-aus-sub', nota);
    } else {
      setText('kpi-valor-sub', 'costo total calculado desde salarios');
      setText('kpi-valor-he-sub', 'costo monetario HE + recargos del período');
      setText('kpi-valor-aus-sub', 'costo monetario días de ausencia del período');
    }

    // Empleados activos / inactivos
    if (kpis.empleados_activos != null) {
      setText('kpi-activos', formatNumber(kpis.empleados_activos));
      const inact = kpis.empleados_inactivos ?? 0;
      const subEl = document.getElementById('kpi-activos-sub');
      if (subEl) subEl.textContent = `${inact} inactivo${inact !== 1 ? 's' : ''} en el período`;
    }

    // Deltas vs período anterior
    renderDelta('kpi-delta-nov', kpis.delta_novedades);
    renderDelta('kpi-delta-emp', kpis.delta_empleados);
    renderDelta('kpi-delta-val', kpis.delta_valor);
  } catch (e) {
    console.error('Error KPIs:', e);
  }
}

function renderDelta(id, pct) {
  const el = document.getElementById(id);
  if (!el) return;
  if (pct == null) { el.textContent = ''; return; }
  const up = pct > 0;
  const arrow = up ? '▲' : '▼';
  const sign  = up ? '+' : '';
  el.className = `kpi-delta ${up ? 'up' : 'down'}`;
  el.textContent = `${arrow} ${sign}${pct}% vs período ant.`;
}

function setText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value;
}

// ── Resumen por área (Panel Ejecutivo) ────────────────────────

let _areaData = [];

async function loadResumenPorArea() {
  const tbody = document.getElementById('area-tbody');
  if (!tbody) return;
  tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:#94a3b8;padding:20px">Cargando…</td></tr>';
  try {
    _areaData = await API.getResumenPorArea(currentFilters);
    _renderAreaTabla(_areaData);
    const footer = document.getElementById('area-footer');
    const totalAreas = _areaData.length;
    const totalEmp   = _areaData.reduce((s, r) => s + r.total_empleados, 0);
    const totalAct   = _areaData.reduce((s, r) => s + r.activos, 0);
    if (footer) footer.textContent = `${totalAreas} áreas · ${totalEmp} empleados en total · ${totalAct} activos`;
  } catch (e) {
    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:#ef4444;padding:20px">Error cargando resumen</td></tr>';
    console.error('Error resumen área:', e);
  }
}

function _renderAreaTabla(rows) {
  const tbody = document.getElementById('area-tbody');
  if (!tbody) return;
  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:#94a3b8;padding:20px">Sin datos</td></tr>';
    return;
  }
  tbody.innerHTML = rows.map(r => {
    const pct    = r.pct_activos ?? 0;
    const barClr = pct >= 80 ? '#22c55e' : pct >= 50 ? '#f59e0b' : '#ef4444';
    const bar    = `<div style="display:flex;align-items:center;gap:6px">
      <div style="flex:1;background:#f1f5f9;border-radius:4px;height:8px;overflow:hidden">
        <div style="width:${pct}%;background:${barClr};height:100%;border-radius:4px;transition:width .4s"></div>
      </div>
      <span style="font-size:.75rem;font-weight:700;color:${barClr};min-width:38px">${pct}%</span>
    </div>`;
    return `<tr>
      <td style="font-weight:600;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${r.area}">${r.area}</td>
      <td style="text-align:right;font-weight:700">${formatNumber(r.total_empleados)}</td>
      <td style="text-align:right"><span style="color:#16a34a;font-weight:600">${formatNumber(r.activos)}</span></td>
      <td style="text-align:right"><span style="color:${r.inactivos > 0 ? '#dc2626' : '#94a3b8'};font-weight:600">${formatNumber(r.inactivos)}</span></td>
      <td>${bar}</td>
      <td style="text-align:right;color:#64748b">${formatNumber(r.total_novedades)}</td>
      <td style="color:#64748b;font-size:.8rem">${formatPeriodo(r.ultimo_periodo)}</td>
    </tr>`;
  }).join('');
}

function buscarArea(q) {
  const ql = q.toLowerCase();
  const filtered = ql ? _areaData.filter(r => r.area.toLowerCase().includes(ql)) : _areaData;
  _renderAreaTabla(filtered);
}

// ── Lista empleados (Panel Ejecutivo) ─────────────────────────

let _empleadosData = [];   // caché de la última carga
let _empFiltroEstado = 'todos';
let _empFiltroArea   = '';     // área seleccionada en el filtro inline

async function loadEmpleadosLista() {
  const tbody = document.getElementById('emp-tbody');
  if (!tbody) return;
  tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:#94a3b8;padding:20px">Cargando…</td></tr>';
  try {
    const params = { ...currentFilters, tipo_novedad: null };
    const data = await API.getEmpleados(params);
    _empleadosData   = data.data || [];
    _empFiltroEstado = 'todos';

    // Poblar select de áreas con los valores únicos de la carga
    const areaSelect = document.getElementById('emp-filter-area');
    if (areaSelect) {
      const areas = [...new Set(_empleadosData.map(r => r.area).filter(Boolean))].sort();
      areaSelect.innerHTML = '<option value="">Todas las áreas</option>' +
        areas.map(a => `<option value="${a}">${a}</option>`).join('');
      // Sincronizar con el filtro del panel superior si hay área activa
      areaSelect.value = currentFilters.area || '';
      _empFiltroArea   = currentFilters.area || '';
    }

    // Contadores en badges
    setText('emp-cnt-activos',   data.activos);
    setText('emp-cnt-inactivos', data.inactivos);

    _renderEmpleadosTabla(_empleadosData);
    _setEmpBadgeSelected('todos');

    const footer = document.getElementById('emp-footer');
    if (footer) footer.textContent = `${data.total} empleados en el período — ${data.activos} activos, ${data.inactivos} inactivos`;
  } catch (e) {
    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:#ef4444;padding:20px">Error cargando empleados</td></tr>';
    console.error('Error empleados:', e);
  }
}

function _renderEmpleadosTabla(rows) {
  const tbody = document.getElementById('emp-tbody');
  if (!tbody) return;
  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:#94a3b8;padding:20px">Sin registros</td></tr>';
    return;
  }
  tbody.innerHTML = rows.map(r => `
    <tr>
      <td style="font-family:monospace;color:#64748b">${r.cedula ?? '—'}</td>
      <td title="${r.nombre ?? ''}">${r.nombre ?? '—'}</td>
      <td title="${r.area ?? ''}">${r.area ?? '—'}</td>
      <td title="${r.cargo ?? ''}">${r.cargo ?? '—'}</td>
      <td>${formatPeriodo(r.ultimo_periodo)}</td>
      <td title="${r.ultima_novedad ?? ''}" style="color:#64748b;font-size:.75rem">${r.ultima_novedad ?? '—'}</td>
      <td><span class="emp-badge-${r.estado}">${r.estado === 'activo' ? '● Activo' : '● Inactivo'}</span></td>
    </tr>`).join('');
}

function _aplicarFiltrosEmpleados() {
  const buscar = (document.getElementById('emp-buscar')?.value || '').toLowerCase();
  let rows = _empleadosData;
  if (_empFiltroEstado !== 'todos') rows = rows.filter(r => r.estado === _empFiltroEstado);
  if (_empFiltroArea)               rows = rows.filter(r => r.area === _empFiltroArea);
  if (buscar) rows = rows.filter(r =>
    (r.nombre ?? '').toLowerCase().includes(buscar) ||
    (r.cedula ?? '').includes(buscar)
  );
  _renderEmpleadosTabla(rows);
}

function filtrarEmpleados(estado) {
  _empFiltroEstado = estado;
  _setEmpBadgeSelected(estado);
  _aplicarFiltrosEmpleados();
}

function filtrarEmpleadosPorArea(area) {
  _empFiltroArea = area;
  _aplicarFiltrosEmpleados();
}

function buscarEmpleados(q) {
  _aplicarFiltrosEmpleados();
}

function _setEmpBadgeSelected(estado) {
  ['todos','activo','inactivo'].forEach(e => {
    const badge = document.getElementById(`emp-badge-${e}s`) || document.getElementById(`emp-badge-${e}`);
    if (!badge) return;
    badge.classList.remove('activo-selected','inactivo-selected','todos-selected');
  });
  const selMap = { todos: 'emp-badge-todos', activo: 'emp-badge-activos', inactivo: 'emp-badge-inactivos' };
  const el = document.getElementById(selMap[estado]);
  if (el) el.classList.add(`${estado}-selected`);
}

// ── Gráficas (Panel Ejecutivo) ────────────────────────────────

async function loadCharts() {
  const ids = ['chart-tipo', 'chart-area', 'chart-trend', 'chart-valor', 'chart-pie'];
  ids.forEach(showChartLoading);
  try {
    const filters = { ...currentFilters, tipo_novedad: null };
    const [tipo, area, trend, valorCategoria] = await Promise.all([
      API.getChartTipo(filters),
      API.getChartArea(filters),
      API.getChartTrend(filters),
      API.getChartValorCategoria(filters),
    ]);

    renderChart('chart-tipo', tipo, {
      layout: { padding: { top: 22 } },
      plugins: {
        legend: { display: false },
        datalabels: {
          display: true,
          anchor: 'end',
          align: 'end',
          color: '#2c4770',
          font: { size: 11, weight: '600' },
          formatter: (v) => v > 0 ? formatNumber(v) : '',
        },
      },
    });

    renderChart('chart-area', area, {
      indexAxis: 'y',
      layout: { padding: { right: 42 } },
      plugins: {
        legend: { display: false },
        datalabels: {
          display: true,
          anchor: 'end',
          align: 'end',
          color: '#2c4770',
          font: { size: 11, weight: '600' },
          formatter: (v) => v > 0 ? formatNumber(v) : '',
        },
      },
    });

    renderChart('chart-trend', trend);

    // Gráfica de impacto económico por categoría (doughnut con valores en COP)
    renderChart('chart-valor', valorCategoria, {
      plugins: {
        legend: { position: 'right', labels: { boxWidth: 12, font: { size: 11 } } },
        datalabels: {
          display: true,
          color: '#fff',
          font: { size: 10, weight: '700' },
          formatter: (v, ctx) => {
            const total = ctx.dataset.data.reduce((a, b) => a + b, 0);
            const pct = total > 0 ? ((v / total) * 100).toFixed(1) : 0;
            return pct > 5 ? pct + '%' : '';
          },
        },
      },
    });

    renderChart('chart-pie', {
      chart_type: 'doughnut',
      labels: tipo.labels,
      series: [{ data: tipo.series?.[0]?.data || [] }],
    }, { plugins: { legend: { position: 'right', labels: { boxWidth: 12, font: { size: 11 } } } } });
  } catch (e) {
    console.error('Error gráficas:', e);
  } finally {
    ids.forEach(hideChartLoading);
  }
}

// ── Panel Operativo ───────────────────────────────────────────

async function loadPanelOperativo() {
  try {
    const panelFilters = {
      area:    currentFilters.area    || null,
      sede:    currentFilters.sede    || null,
      periodo: currentFilters.periodo || null,
    };
    const data = await API.getAlerts(panelFilters);

    // KPIs
    setText('op-total-ingresados', formatNumber(data.total_ingresados));
    setText('op-total-validos',    formatNumber(data.total_validos));
    setText('op-total-alertas',    formatNumber(data.total_con_alerta));
    setText('op-total-invalidos',  formatNumber(data.total_invalidos));

    // Resumen por severidad
    setText('op-alta',  data.alta);
    setText('op-media', data.media);
    setText('op-baja',  data.baja);

    // Punto rojo en tab si hay alertas altas
    const dot = document.getElementById('alert-dot');
    if (dot) dot.style.display = data.alta > 0 ? 'inline-block' : 'none';

    // Embudo
    const total = data.total_ingresados || 1;
    renderFunnel('validos',   data.total_validos,    total, formatNumber(data.total_validos));
    renderFunnel('alertas',   data.total_con_alerta, total, formatNumber(data.total_con_alerta));
    renderFunnel('invalidos', data.total_invalidos,  total, formatNumber(data.total_invalidos));
    setText('funnel-cnt-ingresados', formatNumber(data.total_ingresados));

    // Lista de alertas
    const listEl = document.getElementById('op-alertas-list');
    if (listEl) {
      if (!data.alertas?.length) {
        listEl.innerHTML = '<div style="text-align:center;padding:20px;color:var(--muted)"><i class="bi bi-check-circle" style="font-size:1.5rem"></i><br>Sin alertas activas</div>';
      } else {
        listEl.innerHTML = data.alertas.map(a => `
          <div class="alert-card ${a.severidad}">
            <div class="alert-card-icon">${a.severidad === 'alta' ? '🔴' : a.severidad === 'media' ? '🟡' : '🟢'}</div>
            <div class="alert-card-body">
              <strong>${_alertTitulo(a.tipo)} — ${formatNumber(a.cantidad)} caso(s)</strong>
              <span>${a.mensaje}</span>
            </div>
          </div>`).join('');
      }
    }
    // Tabla detallada de alertas
    await loadAlertasDetalle(panelFilters);
  } catch (e) {
    console.error('Error panel operativo:', e);
    const listEl = document.getElementById('op-alertas-list');
    if (listEl) listEl.innerHTML = `<div style="color:var(--danger);padding:12px">${e.message}</div>`;
  }
}

let _alertasDetalleCache = [];

async function loadAlertasDetalle(panelFilters) {
  const tbody = document.getElementById('op-detalle-tbody');
  if (!tbody) return;
  // Bind del filtro una sola vez
  const sel = document.getElementById('op-alerta-filtro');
  if (sel && !sel.dataset.bound) {
    sel.addEventListener('change', renderAlertasDetalle);
    sel.dataset.bound = '1';
  }
  // Bind del botón exportar una sola vez
  const btn = document.getElementById('btn-export-alertas');
  if (btn && !btn.dataset.bound) {
    btn.addEventListener('click', exportAlertasExcel);
    btn.dataset.bound = '1';
  }
  try {
    const data = await API.getAlertsDetalle(panelFilters);
    _alertasDetalleCache = data.detalle || [];
    renderAlertasDetalle();
  } catch (e) {
    console.error('Error detalle alertas:', e);
    tbody.innerHTML = `<tr><td colspan="10" style="color:var(--danger);padding:12px">${e.message}</td></tr>`;
  }
}

function renderAlertasDetalle() {
  const tbody = document.getElementById('op-detalle-tbody');
  const countEl = document.getElementById('op-detalle-count');
  const filtro = document.getElementById('op-alerta-filtro')?.value || '';
  if (!tbody) return;

  const rows = filtro
    ? _alertasDetalleCache.filter(r => r.tipo_alerta === filtro)
    : _alertasDetalleCache;

  if (countEl) countEl.textContent = `${rows.length} registro(s)`;

  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="10" style="text-align:center;padding:20px;color:var(--muted)"><i class="bi bi-check-circle"></i> Sin registros con alerta</td></tr>';
    return;
  }

  const badge = (sev) => sev === 'alta' ? '🔴' : sev === 'media' ? '🟡' : '🟢';
  tbody.innerHTML = rows.map(r => `
    <tr>
      <td>${badge(r.severidad)} ${r.tipo_alerta}</td>
      <td>${r.cedula ?? '—'}</td>
      <td>${r.nombre ?? '—'}</td>
      <td>${r.area ?? '—'}</td>
      <td>${r.tipo_novedad ?? '—'}</td>
      <td>${r.periodo ?? '—'}</td>
      <td>${r.fecha_inicio ?? '—'}</td>
      <td style="text-align:right">${r.dias ?? '—'}</td>
      <td style="color:var(--muted)">${r.motivo ?? '—'}</td>
      <td style="font-size:.72rem;color:var(--muted)">${r.archivo_origen ?? '—'}</td>
    </tr>`).join('');
}

function exportAlertasExcel() {
  // Respeta el filtro de tipo de alerta activo en la tabla
  const filtro = document.getElementById('op-alerta-filtro')?.value || '';
  const rows = filtro
    ? _alertasDetalleCache.filter(r => r.tipo_alerta === filtro)
    : _alertasDetalleCache;

  if (!rows.length) {
    showToast('No hay registros con alerta para exportar.', 'warning');
    return;
  }

  const headers = ['Alerta', 'Severidad', 'Cédula', 'Nombre', 'Área',
                   'Tipo Novedad', 'Período', 'Fecha Inicio', 'Fecha Fin',
                   'Cantidad', 'Unidad', 'Motivo', 'Archivo'];

  // Escape: comillas dobladas y campo entre comillas (separador ;)
  const esc = (v) => {
    if (v == null) return '';
    const s = String(v).replace(/"/g, '""');
    return `"${s}"`;
  };

  const lineas = [headers.map(esc).join(';')];
  rows.forEach(r => {
    lineas.push([
      r.tipo_alerta, r.severidad, r.cedula, r.nombre, r.area,
      r.tipo_novedad, r.periodo, r.fecha_inicio, r.fecha_fin,
      r.dias, r.unidad, r.motivo, r.archivo_origen,
    ].map(esc).join(';'));
  });

  // BOM UTF-8 para que Excel respete los acentos
  const csv = '﻿' + lineas.join('\r\n');
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const per = currentFilters.periodo || 'todos';
  const sufijo = filtro ? `_${filtro.replace(/\s+/g, '-')}` : '';
  const link = document.createElement('a');
  link.href = url;
  link.download = `alertas_${per}${sufijo}.csv`;
  link.click();
  URL.revokeObjectURL(url);
  showToast(`Exportados ${rows.length} registro(s) a Excel.`, 'success');
}

function renderFunnel(key, value, total, label) {
  const bar = document.getElementById(`funnel-bar-${key}`);
  const cnt = document.getElementById(`funnel-cnt-${key}`);
  if (bar) bar.style.width = `${Math.min(100, (value / total) * 100).toFixed(1)}%`;
  if (cnt) cnt.textContent = label;
}

function _alertTitulo(tipo) {
  const map = {
    duplicado:          'Duplicados',
    valor_atipico:      'Valor atípico',
    invalido:           'Registros inválidos',
    he_limite:          'Límite HE excedido',
    sin_fecha:          'Sin fecha',
    area_irregularidades: 'Área con errores',
    solapamiento:       'Solapamiento fechas',
  };
  return map[tipo] || tipo;
}

// ── Panel Ausentismo ──────────────────────────────────────────

async function loadPanelAusentismo() {
  const panelFilters = {
    area:    currentFilters.area    || null,
    sede:    currentFilters.sede    || null,
    periodo: currentFilters.periodo || null,
  };
  const ids = ['chart-aus-areas', 'chart-aus-tendencia', 'chart-aus-tipos'];
  ids.forEach(showChartLoading);
  try {
    const data = await API.getPanelAusent(panelFilters);

    setText('aus-dias',        formatNumber(data.total_dias_perdidos));
    setText('aus-eventos',     formatNumber(data.total_eventos));
    setText('aus-empleados',   formatNumber(data.empleados_con_ausencia));
    setText('aus-recurrentes', formatNumber(data.empleados_recurrentes));

    // KPI valor total
    setText('aus-valor-total', formatCOP(data.total_valor_ausentismo));

    // Tasa de ausentismo = (días perdidos / (empleados activos × 20 días hábiles)) × 100
    const diasHabiles = 20; // promedio de días hábiles/mes
    const tasa = data.empleados_activos_mes > 0
      ? ((data.total_dias_perdidos / (diasHabiles * data.empleados_activos_mes)) * 100).toFixed(1) + '%'
      : '—';
    setText('aus-tasa', tasa);

    // Tabla desglose por tipo
    const tbodyAus = document.getElementById('aus-valor-tabla');
    if (tbodyAus) {
      if (!data.valor_por_tipo?.length) {
        tbodyAus.innerHTML = '<tr><td colspan="5" style="text-align:center;padding:12px;color:var(--muted)">Sin datos de salario disponibles</td></tr>';
      } else {
        tbodyAus.innerHTML = data.valor_por_tipo.map(t => `
          <tr>
            <td style="font-size:.8rem;font-weight:600">${t.tipo}</td>
            <td style="text-align:right">${formatNumber(t.dias)}</td>
            <td style="text-align:right">${formatNumber(t.eventos)}</td>
            <td style="text-align:right;font-weight:700;color:${t.remunerado ? '#166534' : '#9ca3af'}">${formatCOP(t.valor)}</td>
            <td style="text-align:center">
              <span class="${t.remunerado ? 'eco-badge-rem' : 'eco-badge-norem'}">${t.remunerado ? 'Sí' : 'No'}</span>
            </td>
          </tr>`).join('');
      }
    }

    renderChart('chart-aus-areas', data.chart_areas, {
      indexAxis: 'y',
      plugins: { legend: { display: false },
        datalabels: { display: true, anchor: 'end', align: 'end', color: '#2c4770',
          font: { size: 10, weight: '600' }, formatter: v => v > 0 ? formatNumber(v) : '' } },
    });
    renderChart('chart-aus-tendencia', data.chart_tendencia);
    renderChart('chart-aus-tipos', data.chart_tipos, {
      plugins: { legend: { position: 'right', labels: { boxWidth: 12, font: { size: 11 } } } },
    });

    // Cargar tabla de empleados con ausentismo
    await loadAusentismoEmpleados(panelFilters);
  } catch (e) {
    console.error('Error panel ausentismo:', e);
  } finally {
    ids.forEach(hideChartLoading);
  }
}

// ── Panel Horas Extras ────────────────────────────────────────

async function loadPanelHorasExtras() {
  const panelFilters = {
    area:    currentFilters.area    || null,
    sede:    currentFilters.sede    || null,
    periodo: currentFilters.periodo || null,
  };
  const ids = ['chart-he-tipos', 'chart-he-tendencia', 'chart-he-areas'];
  ids.forEach(showChartLoading);
  try {
    const data = await API.getPanelHorasExt(panelFilters);

    setText('he-total',     `${formatNumber(data.total_horas)} h`);
    setText('he-eventos',   formatNumber(data.total_eventos));
    setText('he-empleados', formatNumber(data.empleados_con_he));
    setText('he-exceso',    formatNumber(data.empleados_exceso_48h));

    // KPI valor total pagado
    setText('he-valor-total', formatCOP(data.total_valor_pagado));

    // Tabla desglose por tipo con factores
    const tbodyHe = document.getElementById('he-valor-tabla');
    if (tbodyHe) {
      if (!data.valor_por_tipo?.length) {
        tbodyHe.innerHTML = '<tr><td colspan="5" style="text-align:center;padding:12px;color:var(--muted)">Sin datos de salario disponibles</td></tr>';
      } else {
        tbodyHe.innerHTML = data.valor_por_tipo.map(t => `
          <tr>
            <td style="font-size:.8rem;font-weight:600">${t.tipo}</td>
            <td style="text-align:right">${formatNumber(t.horas)} h</td>
            <td style="text-align:right">${formatNumber(t.eventos)}</td>
            <td style="text-align:center"><span style="font-size:.78rem;font-weight:700;color:#6d28d9">×${t.factor}</span></td>
            <td style="text-align:right;font-weight:700;color:#991b1b">${formatCOP(t.valor)}</td>
          </tr>`).join('');
      }
    }

    renderChart('chart-he-tipos', data.chart_tipos, {
      layout: { padding: { top: 22 } },
      plugins: { legend: { display: false },
        datalabels: { display: true, anchor: 'end', align: 'end', color: '#2c4770',
          font: { size: 10, weight: '600' }, formatter: v => v > 0 ? formatNumber(v) : '' } },
    });
    renderChart('chart-he-tendencia', data.chart_tendencia);
    renderChart('chart-he-areas', data.chart_areas, {
      indexAxis: 'y',
      plugins: { legend: { display: false },
        datalabels: { display: true, anchor: 'end', align: 'end', color: '#2c4770',
          font: { size: 10, weight: '600' }, formatter: v => v > 0 ? formatNumber(v) : '' } },
    });

    // Tabla top empleados con valor
    const tbody = document.getElementById('he-top-table');
    if (tbody) {
      if (!data.top_empleados?.length) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;padding:20px;color:var(--muted)">Sin datos</td></tr>';
      } else {
        tbody.innerHTML = data.top_empleados.map(e => `
          <tr>
            <td style="font-size:.8rem">${e.nombre || e.cedula}</td>
            <td><span class="badge badge-area" style="font-size:.7rem">${e.area || '—'}</span></td>
            <td style="text-align:right;font-weight:700;color:${e.excede_limite ? 'var(--danger)' : 'var(--text)'}">
              ${formatNumber(e.horas)} h
            </td>
            <td style="text-align:right;font-size:.78rem;font-weight:600;color:#991b1b">
              ${formatCOP(e.valor)}
            </td>
            <td>
              <span class="badge ${e.excede_limite ? 'badge-excede' : 'badge-ok-he'}">
                ${e.excede_limite ? '⚠ Excede' : '✓ OK'}
              </span>
            </td>
          </tr>`).join('');
      }
    }
  } catch (e) {
    console.error('Error panel horas extras:', e);
  } finally {
    ids.forEach(hideChartLoading);
  }
}

// ── Tabla de datos ────────────────────────────────────────────

async function loadTable() {
  const tbody = document.getElementById('table-body');
  if (!tbody) return;
  tbody.innerHTML = '<tr><td colspan="11" style="text-align:center;padding:40px;color:var(--muted)"><span class="spinner"></span> Cargando...</td></tr>';

  try {
    const params = {
      ...currentFilters,
      page: tableState.page,
      page_size: tableState.pageSize,
      sort_by: tableState.sortBy,
      sort_dir: tableState.sortDir,
    };
    const result = await API.getTable(params);
    tableState.total = result.total;
    renderTable(result.data);
    renderPagination();
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="11" style="text-align:center;padding:40px;color:var(--danger)"><i class="bi bi-exclamation-triangle"></i> ${e.message}</td></tr>`;
  }
}

function renderTable(rows) {
  const tbody = document.getElementById('table-body');
  if (!tbody) return;

  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="11" style="text-align:center;padding:48px;color:var(--muted)"><i class="bi bi-inbox"></i> No se encontraron registros con los filtros aplicados</td></tr>';
    return;
  }

  tbody.innerHTML = rows.map(r => {
    const unidad = r.unidad || 'dias';
    let cantLabel = '—';
    if (r.dias != null) {
      if (unidad === 'horas') cantLabel = `${r.dias} h`;
      else if (unidad === 'valor') cantLabel = formatNumber(r.dias);
      else cantLabel = `${r.dias} d`;
    }
    return `
    <tr>
      <td style="font-family:monospace;font-size:.8rem">${r.cedula || '—'}</td>
      <td>${r.nombre_empleado || '—'}</td>
      <td><span class="badge badge-area">${r.area || '—'}</span></td>
      <td style="font-size:.8rem;color:var(--muted)">${r.sede || '—'}</td>
      <td><span class="badge badge-tipo">${r.tipo_novedad || '—'}</span></td>
      <td style="font-size:.8rem">${formatDate(r.fecha_inicio)}</td>
      <td style="font-size:.8rem">${formatDate(r.fecha_fin)}</td>
      <td style="text-align:right">${cantLabel}</td>
      <td style="text-align:right;font-family:monospace;font-size:.8rem">${r.valor != null ? formatCOP(r.valor) : '—'}</td>
      <td><span class="badge badge-periodo">${r.periodo || '—'}</span></td>
      <td style="font-size:.75rem;color:var(--muted);max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${r.archivo_origen || '—'}</td>
    </tr>`;
  }).join('');
}

function renderPagination() {
  const totalPages = Math.ceil(tableState.total / tableState.pageSize);
  const info = document.getElementById('page-info');
  const btnPrev = document.getElementById('btn-prev');
  const btnNext = document.getElementById('btn-next');
  const start = (tableState.page - 1) * tableState.pageSize + 1;
  const end   = Math.min(tableState.page * tableState.pageSize, tableState.total);

  if (info) info.textContent = `Mostrando ${formatNumber(start)}–${formatNumber(end)} de ${formatNumber(tableState.total)} registros`;
  if (btnPrev) btnPrev.disabled = tableState.page <= 1;
  if (btnNext) btnNext.disabled = tableState.page >= totalPages;
}

document.addEventListener('click', (e) => {
  if (e.target.id === 'btn-prev' || e.target.closest('#btn-prev')) {
    if (tableState.page > 1) { tableState.page--; loadTable(); }
  }
  if (e.target.id === 'btn-next' || e.target.closest('#btn-next')) {
    tableState.page++;
    loadTable();
  }
});

// ── Ordenamiento de tabla ─────────────────────────────────────

function initTableSorting() {
  document.querySelectorAll('.sortable').forEach(th => {
    th.addEventListener('click', () => {
      const col = th.dataset.col;
      if (tableState.sortBy === col) {
        tableState.sortDir = tableState.sortDir === 'asc' ? 'desc' : 'asc';
      } else {
        tableState.sortBy = col;
        tableState.sortDir = 'asc';
      }
      document.querySelectorAll('.sortable').forEach(h => h.classList.remove('sorted-asc','sorted-desc'));
      th.classList.add(`sorted-${tableState.sortDir}`);
      tableState.page = 1;
      loadTable();
    });
  });
}

// ── Exportación ───────────────────────────────────────────────

document.getElementById('btn-export-excel')?.addEventListener('click', () => {
  const params = new URLSearchParams(Object.fromEntries(
    Object.entries(currentFilters).filter(([, v]) => v)
  ));
  const link = document.createElement('a');
  link.href = `${window.location.origin}/api/export/excel?${params}`;
  link.target = '_blank';
  link.click();
});

document.getElementById('btn-export-pdf')?.addEventListener('click', () => {
  const params = new URLSearchParams(Object.fromEntries(
    Object.entries(currentFilters).filter(([, v]) => v)
  ));
  const link = document.createElement('a');
  link.href = `${window.location.origin}/api/export/pdf?${params}`;
  link.target = '_blank';
  link.click();
});

// ── ETL manual (solo admin) ───────────────────────────────────

document.getElementById('btn-run-etl')?.addEventListener('click', async () => {
  if (!confirm('¿Desea iniciar el proceso de carga ahora? Esto puede tardar varios minutos.')) return;
  try {
    await API.triggerETL();
    showToast('Proceso ETL iniciado. Los datos se actualizarán en breve.', 'success');
    setTimeout(() => loadPanel(activePanel), 8000);
  } catch (e) {
    showToast('Error al iniciar el proceso: ' + e.message, 'danger');
  }
});

document.getElementById('btn-logout')?.addEventListener('click', logout);

// ── Tabla de Ausentismo Empleados ────────────────────────────────

let ausentismoEmpleadosCache = [];

async function loadAusentismoEmpleados(panelFilters) {
  const tbody = document.getElementById('aus-emp-tbody');
  if (!tbody) {
    console.warn('No se encontró el elemento aus-emp-tbody en el DOM');
    return;
  }

  try {
    console.log('Cargando datos de ausentismo con filtros:', panelFilters);

    const data = await API.getAusentismoEmpleados(panelFilters);
    console.log('Respuesta de API ausentismo:', data);

    ausentismoEmpleadosCache = data.data || [];
    console.log('Registros cargados:', ausentismoEmpleadosCache.length);

    renderAusentismoEmpleados(ausentismoEmpleadosCache);

    const footer = document.getElementById('aus-emp-footer');
    if (footer) {
      footer.textContent = `Total: ${formatNumber(data.total || 0)} registros`;
    }
  } catch (e) {
    console.error('Error cargando tabla ausentismo:', e);
    console.error('Stack:', e.stack);
    tbody.innerHTML = '<tr><td colspan="10" style="text-align:center;padding:20px;color:#dc2626">Error al cargar datos: ' + (e.message || 'Error desconocido') + '</td></tr>';
  }
}

function renderAusentismoEmpleados(records) {
  const tbody = document.getElementById('aus-emp-tbody');
  if (!tbody) return;

  if (!records || records.length === 0) {
    tbody.innerHTML = '<tr><td colspan="10" style="text-align:center;padding:20px;color:var(--muted)">No hay registros de ausentismo</td></tr>';
    return;
  }

  tbody.innerHTML = records.map(r => `
    <tr>
      <td>${r.cedula}</td>
      <td>${r.nombre}</td>
      <td>${r.area}</td>
      <td>${r.sede}</td>
      <td style="font-size:.8rem;font-weight:600">${r.tipo_novedad}</td>
      <td>${r.fecha_inicio}</td>
      <td>${r.fecha_fin}</td>
      <td style="text-align:right;font-weight:600">${formatNumber(r.dias)}</td>
      <td style="text-align:right">${formatCOP(r.valor)}</td>
      <td>${r.periodo}</td>
    </tr>
  `).join('');
}

function buscarAusentismoEmpleados(query) {
  if (!query) {
    renderAusentismoEmpleados(ausentismoEmpleadosCache);
    return;
  }

  const filtered = ausentismoEmpleadosCache.filter(r =>
    r.cedula.toLowerCase().includes(query.toLowerCase()) ||
    r.nombre.toLowerCase().includes(query.toLowerCase())
  );
  renderAusentismoEmpleados(filtered);
}
