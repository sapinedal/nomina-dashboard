"""Rate limiting (SEC-4) — protección anti-fuerza-bruta / anti-abuso.

Se aplica por decorador en endpoints puntuales (login, disparo de ETL), no
como límite global: el dashboard dispara ~10 requests en paralelo al cargar,
y un límite global los rompería.
"""
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from fastapi import Request
from fastapi.responses import JSONResponse

from app.config import settings


def client_ip(request: Request) -> str:
    """Clave del rate limiter = IP real del cliente.

    En producción la app corre detrás de nginx, que fija X-Forwarded-For con
    `$proxy_add_x_forwarded_for` (ver nginx/nginx.conf). Esa directiva
    APPENDEA el remote_addr real que vio nginx al FINAL de cualquier valor
    que el cliente haya mandado. Por eso la clave se toma de la ÚLTIMA
    entrada del header -- es la única que nginx garantiza y que el cliente no
    puede falsificar.

    Tomar la PRIMERA entrada sería vulnerable a spoofing: un atacante enviaría
    `X-Forwarded-For: <ip-rotada>` y nginx la conservaría como primera entrada,
    dándole un bucket nuevo por cada request y evadiendo el límite por completo.

    Sin el header (dev local contra uvicorn directo, sin nginx) cae a
    request.client.host.

    Nota de despliegue: esto asume UN salto de proxy de confianza (nginx). Si
    Dokploy introduce un proxy adicional (Traefik) delante de nginx, la última
    entrada pasaría a ser la IP de nginx y habría que ajustar cuántos saltos
    descartar. Verificar contra la topología real de Dokploy antes de confiar
    en el conteo por-IP en producción.
    """
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[-1].strip()
    return get_remote_address(request)


limiter = Limiter(
    key_func=client_ip,
    # Redis como almacenamiento compartido: con varios workers de uvicorn
    # (ver Dockerfile --workers) un contador en memoria daría límites N× más
    # laxos, uno por worker. Redis lo mantiene consistente entre todos.
    storage_uri=settings.REDIS_URL,
    # Resiliencia ante caída de Redis: slowapi conmuta transparentemente a un
    # contador EN MEMORIA y sigue limitando (por worker) hasta que Redis
    # vuelve. Misma filosofía que SEC-3 (Redis no es dependencia dura) pero
    # mejor que simplemente ignorar el límite: no se pierde la protección
    # anti-fuerza-bruta durante el incidente, y sobre todo NO devuelve 500.
    #
    # Verificado en vivo (SEC-4): sin in_memory_fallback, un Redis caído
    # producía 500 en cada login -- slowapi tragaba el error de storage pero
    # dejaba request.state.view_rate_limit sin setear y luego lo leía sin
    # guarda (KeyError). El fallback re-ejecuta el chequeo y sí lo setea.
    in_memory_fallback_enabled=True,
    # Último recurso si incluso el fallback en memoria fallara (prácticamente
    # imposible): dejar pasar en vez de 500.
    swallow_errors=True,
    enabled=settings.RATE_LIMIT_ENABLED,
)


async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Respuesta 429 en español y consistente con el resto de la API
    (campo `detail`, que el frontend ya sabe mostrar)."""
    return JSONResponse(
        status_code=429,
        content={"detail": "Demasiadas solicitudes. Espera un momento e intenta de nuevo."},
    )
