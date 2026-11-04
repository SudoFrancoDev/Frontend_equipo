"""
Cabeceras de seguridad de las respuestas de la API y verificación del origen.

- Cabeceras: impiden que el navegador interprete las respuestas como otro tipo de contenido,
  que se incrusten en iframes y que se guarden en caché los datos de la cuenta.
  Las del frontend (CSP, HSTS) las pone CloudFront: deploy/cloudfront-security-headers.json.
- ORIGIN_VERIFY_SECRET: si está definido, solo se atienden peticiones que traigan el encabezado
  X-Origin-Verify con ese valor (CloudFront lo añade como encabezado de origen). Así nadie puede
  saltarse CloudFront llamando directo al ALB por HTTP. /health queda exento para el health check del ALB.
"""
import hmac
import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

ORIGIN_VERIFY_HEADER = "x-origin-verify"

API_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Resource-Policy": "same-site",
}
# Las respuestas JSON no cargan recursos; /docs sí (Swagger desde un CDN), por eso no lleva CSP
API_CSP = "default-src 'none'; frame-ancestors 'none'"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, api_prefix: str = "", docs_paths: tuple = ()):
        super().__init__(app)
        self.auth_prefix = f"{api_prefix}/auth"
        self.docs_paths = docs_paths

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        for name, value in API_HEADERS.items():
            response.headers.setdefault(name, value)
        path = request.url.path
        if not any(path.startswith(p) for p in self.docs_paths):
            response.headers.setdefault("Content-Security-Policy", API_CSP)
        if path.startswith(self.auth_prefix):
            response.headers["Cache-Control"] = "no-store"
        return response


class OriginVerifyMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, secret: str, exempt_paths: tuple = ()):
        super().__init__(app)
        self.secret = secret.encode()
        self.exempt_paths = exempt_paths

    async def dispatch(self, request, call_next):
        if request.url.path not in self.exempt_paths:
            sent = request.headers.get(ORIGIN_VERIFY_HEADER, "").encode()
            if not hmac.compare_digest(sent, self.secret):
                return JSONResponse(status_code=403, content={"detail": "Acceso no permitido"})
        return await call_next(request)


def origin_verify_secret() -> str:
    return os.getenv("ORIGIN_VERIFY_SECRET", "").strip()
