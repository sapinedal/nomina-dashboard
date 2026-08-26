# Sprint 1 — Cierre DEF-0001…0005 (seguridad / login)

Despliegue hacia `https://nomina.clinicavictoriana.com`.

## DEF-0001 — TLS confiable
El servidor corre sobre Dokploy, cuyo Traefik ya ocupa los puertos 80 y 443 del
host y emite el certificado por Let's Encrypt. Por eso el TLS se termina ahí y
no en nginx:

1. Dominio configurado en Dokploy apuntando al servicio `nginx` (puerto 80).
2. `nginx/nginx.conf` sirve HTTP en la red interna y confía en
   `X-Forwarded-Proto` para HSTS.
3. El servicio `nginx` **no** publica puertos del host.
4. Backend: `COOKIE_SECURE=true`.

En un host sin terminador TLS delante, construir con
`nginx/nginx.standalone-tls.conf`, montar los certificados en `nginx/certs/` y
publicar 80/443.

## DEF-0002 — OpenAPI cerrado
Solo con `EXPOSE_OPENAPI=true`. Default `false` → `/api/openapi.json` 404.

## DEF-0003 — Cookies HttpOnly
Login fija `nb_access_token` + `nb_refresh_token` HttpOnly. El FE usa `credentials:'include'` y no guarda JWT en `localStorage`. Refresh y logout usan las cookies.

## DEF-0004 — Headers
Nginx + middleware FastAPI: HSTS (HTTPS), XCTO, XFO, Referrer-Policy, CSP, Permissions-Policy. `server_tokens off`.

## DEF-0005 — Login vacío
Validación HTML5+JS antes del POST; `formatApiError` mapea `detail[]` de FastAPI.

## Notas de deploy
- El servicio `nginx` no debe publicar 80/443: los tiene Traefik y el despliegue
  aborta con `Bind for 0.0.0.0:80 failed: port is already allocated`.
- Tras merge: rebuild nginx + reiniciar backend; bust de cache FE `?v=20260729a`.
