/**
 * escape-html.js — Escapa texto antes de insertarlo en innerHTML.
 *
 * Los datos de novedades (área, nombre, tipo, observaciones) provienen de
 * archivos Excel de RRHH y de la BD Trazalo — no son texto controlado por
 * el desarrollador. `dashboard.js` construye varias tablas con innerHTML +
 * template literals; sin escapar, un valor de origen que contenga HTML/JS
 * se ejecutaría en el navegador de cualquiera que vea ese dato (XSS
 * almacenado). Verificado en local: un área con
 * `<img src=x onerror=alert(...)>` dispara el alert al renderizar la tabla
 * de Resumen por Área.
 */
function escapeHtml(value) {
  if (value === null || value === undefined) return '';
  return String(value).replace(/[&<>"']/g, (ch) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  }[ch]));
}
