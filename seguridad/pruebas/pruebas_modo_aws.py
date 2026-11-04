"""Comportamiento en modo AWS sin base de datos (no se ejecuta el lifespan)."""
import os
import sys

os.environ.update(APP_MODE="aws", API_PREFIX="/api", CORS_ORIGINS="https://frontend.example",
                  ORIGIN_VERIFY_SECRET="s3cr3t-de-prueba", TRUSTED_PROXY_HOPS="2")
sys.path.insert(0, sys.argv[1])

from fastapi.testclient import TestClient  # noqa: E402
import main  # noqa: E402
from middleware import rate_limit  # noqa: E402

results = []


def check(name, cond, extra=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra else ""))


t = TestClient(main.app)
ok_hdr = {"X-Origin-Verify": "s3cr3t-de-prueba"}
check("/api/docs deshabilitado", t.get("/api/docs", headers=ok_hdr).status_code == 404)
check("/api/openapi.json deshabilitado", t.get("/api/openapi.json", headers=ok_hdr).status_code == 404)
check("health sin cabecera (health check del ALB)", t.get("/api/health").status_code == 200)
check("health no expone el modo", "mode" not in t.get("/api/health").json())
check("petición directa al ALB sin cabecera -> 403", t.get("/api/articles").status_code == 403)
check("cabecera incorrecta -> 403", t.get("/api/articles", headers={"X-Origin-Verify": "x"}).status_code == 403)
check("con cabecera de CloudFront pasa (503 sin datos)", t.get("/api/articles", headers=ok_hdr).status_code == 503)

pre = {"Access-Control-Request-Method": "POST", **ok_hdr}
r = t.options("/api/search", headers={"Origin": "https://atacante.example", **pre})
check("CORS: origen ajeno no autorizado", "access-control-allow-origin" not in r.headers)
r = t.options("/api/search", headers={"Origin": "https://frontend.example", **pre})
check("CORS: CloudFront autorizado",
      r.headers.get("access-control-allow-origin") == "https://frontend.example")


class Req:
    def __init__(self, xff):
        self.headers = {"x-forwarded-for": xff}
        self.client = type("C", (), {"host": "1.1.1.1"})


check("IP real con CloudFront+ALB", rate_limit.client_ip(Req("203.0.113.7, 130.176.0.1")) == "203.0.113.7")
check("XFF falsificado por el cliente se ignora",
      rate_limit.client_ip(Req("6.6.6.6, 203.0.113.7, 130.176.0.1")) == "203.0.113.7")

print(f"\n{sum(results)}/{len(results)} pruebas superadas")
