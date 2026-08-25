# Sprint 1 — Cierre DEF-0001…0005 (seguridad / login)

Despliegue hacia `https://nomina.clinicavictoriana.com`.

## DEF-0001 — TLS confiable
1. Emitir certificado CA pública para el host.
2. Copiar `fullchain.pem` / `privkey.pem` a `nginx/certs/`.
3. `nginx/nginx.conf` termina HTTPS (443) y redirige 80→443.
4. Backend: `COOKIE_SECURE=true`.

## DEF-0002 — OpenAPI cerrado
Solo con `EXPOSE_OPENAPI=true`. Default `false` → `/api/openapi.json` 404.

## DEF-0003 — Cookies HttpOnly
Login fija `nb_access_token` + `nb_refresh_token` HttpOnly. El FE usa `credentials:'include'` y no guarda JWT en `localStorage`. Refresh y logout usan las cookies.

## DEF-0004 — Headers
Nginx + middleware FastAPI: HSTS (HTTPS), XCTO, XFO, Referrer-Policy, CSP, Permissions-Policy. `server_tokens off`.

## DEF-0005 — Login vacío
Validación HTML5+JS antes del POST; `formatApiError` mapea `detail[]` de FastAPI.

## Notas de deploy
- Si aún se termina TLS en otro proxy, usar temporalmente `nginx/nginx.http.dev.conf` y `COOKIE_SECURE` acorde.
- Tras merge: rebuild nginx + reiniciar backend; bust de cache FE `?v=20260729a`.
