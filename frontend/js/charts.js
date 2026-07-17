/**
 * charts.js — Utilidades para crear/actualizar gráficas con Chart.js
 */

const COLORS = [
  '#2c4770','#4f81bd','#c0504d','#9bbb59','#8064a2',
  '#4bacc6','#f79646','#70ad47','#ed7d31','#a5a5a5',
];

const CHART_DEFAULTS = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: {
    // Deshabilitar datalabels globalmente; se activa explícitamente por gráfica
    datalabels: { display: false },
    legend: {
      position: 'bottom',
      labels: { boxWidth: 12, padding: 15, font: { size: 11 } },
    },
    tooltip: {
      backgroundColor: 'rgba(28,47,94,.92)',
      padding: 10,
      titleFont: { size: 12 },
      bodyFont: { size: 11 },
      callbacks: {
        label: (ctx) => {
          const val = ctx.parsed.y ?? ctx.parsed;
          if (typeof val === 'number' && val > 1000) return ` ${formatNumber(val)}`;
          return ` ${val}`;
        },
      },
    },
  },
};

const chartInstances = {};

/**
 * Crear o actualizar una gráfica en un canvas.
 * @param {string} canvasId  - ID del elemento <canvas>
 * @param {object} data      - Respuesta de la API (labels, series, chart_type)
 * @param {object} extraOpts - Opciones adicionales para Chart.js
 */
function renderChart(canvasId, data, extraOpts = {}) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;

  // Destruir instancia previa
  if (chartInstances[canvasId]) {
    chartInstances[canvasId].destroy();
  }

  const type = data.chart_type || 'bar';
  const isLine = type === 'line';
  const isPie = type === 'pie' || type === 'doughnut';

  let datasets;
  if (isPie) {
    datasets = [{
      data: data.series[0]?.data || [],
      backgroundColor: COLORS,
      borderWidth: 2,
      borderColor: '#fff',
    }];
  } else {
    datasets = (data.series || []).map((s, i) => ({
      label: s.label,
      data: s.data,
      backgroundColor: isLine ? 'transparent' : (s.color || COLORS[i]),
      borderColor: s.color || COLORS[i],
      borderWidth: isLine ? 2.5 : 1,
      tension: 0.4,
      fill: isLine,
      pointRadius: isLine ? 3 : 0,
      pointHoverRadius: isLine ? 5 : 0,
      borderRadius: isLine ? 0 : 6,
    }));
  }

  const options = {
    ...CHART_DEFAULTS,
    ...extraOpts,
    plugins: {
      ...CHART_DEFAULTS.plugins,
      ...(extraOpts.plugins || {}),
      title: {
        display: !!data.title,
        text: data.title,
        font: { size: 13, weight: '600' },
        color: '#2c4770',
        padding: { bottom: 8 },
      },
    },
    scales: isPie ? {} : {
      x: {
        grid: { display: false },
        ticks: { font: { size: 10 }, maxRotation: 30 },
      },
      y: {
        beginAtZero: true,
        grid: { color: 'rgba(0,0,0,.05)' },
        ticks: {
          font: { size: 10 },
          callback: (v) => v >= 1000 ? `${(v / 1000).toFixed(0)}k` : v,
        },
      },
      ...(extraOpts.scales || {}),
    },
  };

  chartInstances[canvasId] = new Chart(canvas, {
    type,
    data: { labels: data.labels, datasets },
    options,
  });

  return chartInstances[canvasId];
}

/** Mostrar spinner dentro del contenedor de una gráfica */
function showChartLoading(canvasId) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  const parent = canvas.parentElement;
  if (parent.querySelector('.chart-spinner')) return;
  const spinner = document.createElement('div');
  spinner.className = 'chart-spinner';
  spinner.style.cssText = 'position:absolute;inset:0;background:rgba(255,255,255,.75);z-index:5;border-radius:8px;display:flex;align-items:center;justify-content:center;';
  spinner.innerHTML = '<span class="spinner" style="width:28px;height:28px;border-width:3px"></span>';
  parent.style.position = 'relative';
  parent.appendChild(spinner);
}

function hideChartLoading(canvasId) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  const spinner = canvas.parentElement.querySelector('.chart-spinner');
  if (spinner) spinner.remove();
}
