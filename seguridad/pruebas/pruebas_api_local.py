"""Pruebas contra la API local (http://127.0.0.1:58000). Cada grupo usa una IP distinta vía X-Forwarded-For
(uvicorn confía en 127.0.0.1 como proxy), para que los límites de un grupo no afecten a otro."""
import secrets
import httpx
from urllib.parse import quote

BASE = "http://127.0.0.1:58000"
results = []


def check(name, cond, extra=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra else ""))


def c(ip):
    return httpx.Client(base_url=BASE, headers={"X-Forwarded-For": ip}, timeout=60)


# ── Funcional (regresión tras actualizar dependencias) ──
f = c("10.0.0.1")
r = f.post("/search", json={"query": "machine learning", "top_n": 10})
check("search devuelve 10 resultados", r.status_code == 200 and len(r.json()) == 10, r.status_code)
url = r.json()[0]["url"]
check("articles paginado", f.get("/articles?limit=10&offset=0").json()["limit"] == 10)
check("categories", len(f.get("/categories?limit=6").json()) == 6)
r = f.get(f"/articles/{quote(url, safe='')}/related", params={"top_n": 5})
check("related devuelve 5", r.status_code == 200 and len(r.json()["related"]) == 5, r.status_code)
check("recommend", f.get(f"/recommend/{quote(url, safe='')}").status_code == 200)

# ── H8: validación de entradas ──
check("top_n=1000 rechazado", f.post("/search", json={"query": "ai", "top_n": 1000}).status_code == 422)
check("query de 600 caracteres rechazada", f.post("/search", json={"query": "a" * 600}).status_code == 422)
check("limit=100000 rechazado", f.get("/articles?limit=100000").status_code == 422)
check("offset negativo rechazado", f.get("/articles?offset=-1").status_code == 422)
check("related top_n=500 rechazado", f.get(f"/articles/{quote(url, safe='')}/related?top_n=500").status_code == 422)
check("login con password de 5000 chars rechazado",
      c("10.0.0.9").post("/auth/login", json={"email": "a@b.co", "password": "x" * 5000}).status_code == 422)

# ── Inyección ──
for payload in ["' OR '1'='1", "'; DROP TABLE app.app_user; --", "\" UNION SELECT password_hash FROM app.app_user --"]:
    r = f.get(f"/articles/{quote(payload, safe='')}")
    check(f"SQLi en /articles/<url> -> 404 ({payload[:14]}...)", r.status_code == 404)
    r = c("10.0.0.10").post("/auth/login", json={"email": payload + "@x.co", "password": "x"})
    check(f"SQLi en login -> 401 genérico", r.status_code == 401)
check("tabla de usuarios intacta tras SQLi", f.post("/auth/register", json={}).status_code == 422)

# ── H5: cabeceras ──
h = f.get("/health").headers
check("X-Content-Type-Options", h.get("x-content-type-options") == "nosniff")
check("X-Frame-Options", h.get("x-frame-options") == "DENY")
check("CSP en API", "default-src 'none'" in h.get("content-security-policy", ""))

# ── Autenticación / sesión ──
email = f"user{secrets.token_hex(4)}@example.com"
pw = "Clave$egura123"
a = c("10.0.1.1")
check("registro", a.post("/auth/register", json={"name": "Prueba", "email": email, "password": pw}).status_code == 201)
check("contraseña débil rechazada",
      a.post("/auth/register", json={"name": "P", "email": "x" + email, "password": "abc"}).status_code == 422)
r = a.post("/auth/login", json={"email": email, "password": pw})
tok = r.json()["token"]
check("login OK", r.status_code == 200)
check("Cache-Control no-store en /auth", r.headers.get("cache-control") == "no-store")
auth = {"Authorization": f"Bearer {tok}"}
check("/me con token", a.get("/auth/me", headers=auth).status_code == 200)
check("/me sin token -> 401", a.get("/auth/me").status_code == 401)
check("/me con token inventado -> 401", a.get("/auth/me", headers={"Authorization": "Bearer abc"}).status_code == 401)
check("segunda sesión sin force -> 409", a.post("/auth/login", json={"email": email, "password": pw}).status_code == 409)
r = a.post("/auth/login", json={"email": email, "password": pw, "force": True})
tok2 = r.json()["token"]
check("token anterior invalidado tras force", a.get("/auth/me", headers=auth).status_code == 401)
auth2 = {"Authorization": f"Bearer {tok2}"}
a.post("/auth/logout", headers=auth2)
check("token reutilizado tras logout -> 401", a.get("/auth/me", headers=auth2).status_code == 401)
check("reset con token falso -> 400",
      a.post("/auth/reset-password", json={"token": "falso", "password": pw}).status_code == 400)

# ── H3: enumeración de usuarios ──
e = c("10.0.2.1")
r_exist = e.post("/auth/login", json={"email": email, "password": "Incorrecta#1"})
r_none = e.post("/auth/login", json={"email": "noexiste" + email, "password": "Incorrecta#1"})
check("mismo código correo existente vs inexistente", r_exist.status_code == r_none.status_code == 401)
check("mismo mensaje correo existente vs inexistente", r_exist.json() == r_none.json(), r_exist.json())

# ── Bloqueo tras 5 intentos ──
for _ in range(3):
    e.post("/auth/login", json={"email": email, "password": "Incorrecta#1"})
r = e.post("/auth/login", json={"email": email, "password": "Incorrecta#1"})
check("5º intento fallido bloquea (423)", r.status_code == 423)
check("contraseña correcta rechazada mientras está bloqueada",
      c("10.0.2.2").post("/auth/login", json={"email": email, "password": pw}).status_code == 423)

# ── H4: rate limiting ──
rl = c("10.0.3.1")
codes = [rl.post("/auth/login", json={"email": "x@y.co", "password": "x"}).status_code for _ in range(11)]
check("login: 11ª petición/min -> 429", codes[:10] == [401] * 10 and codes[10] == 429, codes)
r = rl.post("/auth/login", json={"email": "x@y.co", "password": "x"})
check("429 trae Retry-After", "retry-after" in r.headers)
check("otra IP no se ve afectada", c("10.0.3.2").post("/auth/login", json={"email": "x@y.co", "password": "x"}).status_code == 401)
codes = [c("10.0.3.3").post("/auth/register", json={"name": "Spam", "email": f"s{i}@x.co", "password": pw}).status_code
         for i in range(6)]
check("registro: 6º en 15 min -> 429", codes[5] == 429, codes)
codes = [c("10.0.3.4").post("/auth/forgot-password", json={"email": "a@b.co"}).status_code for _ in range(6)]
check("forgot-password: 6º en 15 min -> 429", codes[5] == 429, codes)
codes = [c("10.0.3.5").post("/search", json={"query": "ai", "top_n": 1}).status_code for _ in range(61)]
check("search: 61ª/min -> 429", codes[60] == 429 and set(codes[:60]) == {200})

ok = sum(r for _, r in results)
print(f"\n{ok}/{len(results)} pruebas superadas")
