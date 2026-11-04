"""
Límite de peticiones por IP (ventana deslizante en memoria).

- Frena la fuerza bruta de contraseñas, el registro masivo de cuentas, el abuso del correo de
  recuperación y el gasto en SageMaker del teaser.
- La IP se toma de X-Forwarded-For contando TRUSTED_PROXY_HOPS saltos desde la derecha
  (en AWS: CloudFront + ALB = 2). No se usa request.client.host porque uvicorn, con
  --forwarded-allow-ips "*", lo toma del primer valor del encabezado, que el cliente puede falsificar.
- El contador vive en el proceso: con varias tareas de ECS el límite efectivo es por tarea.
"""
import os
import threading
import time
from collections import deque

from fastapi import HTTPException, Request

TRUSTED_PROXY_HOPS = int(os.getenv("TRUSTED_PROXY_HOPS", "0"))
MAX_TRACKED_KEYS   = 50_000   # tope de memoria: al superarlo se descartan las entradas vencidas

_hits: dict = {}
_lock = threading.Lock()


def client_ip(request: Request) -> str:
    """IP del cliente vista por el primer proxy de confianza (o la del socket si no hay proxies)."""
    if TRUSTED_PROXY_HOPS > 0:
        hosts = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
        if len(hosts) >= TRUSTED_PROXY_HOPS:
            return hosts[-TRUSTED_PROXY_HOPS]
    return request.client.host if request.client else "desconocida"


def _prune(now: float, window: int):
    for key in [k for k, q in _hits.items() if not q or q[-1] <= now - window]:
        del _hits[key]


def rate_limit(bucket: str, max_requests: int, window_seconds: int):
    """
    Dependencia de FastAPI: admite max_requests por IP cada window_seconds en el grupo bucket.
    Responde 429 con Retry-After al superarlo.
    """
    def dependency(request: Request):
        now = time.monotonic()
        key = (bucket, client_ip(request))
        with _lock:
            if len(_hits) > MAX_TRACKED_KEYS:
                _prune(now, window_seconds)
            hits = _hits.setdefault(key, deque())
            while hits and hits[0] <= now - window_seconds:
                hits.popleft()
            if len(hits) >= max_requests:
                retry = int(hits[0] + window_seconds - now) + 1
                raise HTTPException(
                    status_code=429,
                    detail="Demasiadas solicitudes. Espera un momento e inténtalo de nuevo.",
                    headers={"Retry-After": str(retry)},
                )
            hits.append(now)

    return dependency
