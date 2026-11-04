"""Abre cada página con Chromium headless y registra violaciones de CSP y errores de JS.
datara.test se resuelve a 127.0.0.1 para que config.js use /api (como en CloudFront)."""
from playwright.sync_api import sync_playwright

BASE = "http://datara.test:58080"
PAGES = ["index.html", "resultados.html?q=machine+learning", "informacion.html", "login.html"]
problems = []

with sync_playwright() as p:
    browser = p.chromium.launch(args=["--host-resolver-rules=MAP datara.test 127.0.0.1"])
    page = browser.new_page()
    page.on("console", lambda m: m.type in ("error", "warning") and problems.append(f"{page.url}: {m.text}"))
    page.on("pageerror", lambda e: problems.append(f"{page.url}: JS {e}"))
    for path in PAGES:
        page.goto(f"{BASE}/{path}", wait_until="networkidle")
        if path.startswith("resultados"):
            page.wait_for_selector(".article-card", timeout=30000)
            print("resultados: tarjetas renderizadas =", page.locator(".article-card").count())
        if path == "index.html":
            page.wait_for_selector(".article-card", timeout=30000)
            print("index: tarjetas destacadas =", page.locator(".article-card").count())
            fonts = page.evaluate("document.fonts.check('16px \"Plus Jakarta Sans\"')")
            print("index: fuente de Google cargada =", fonts)
    # Login completo en el navegador (registro + sesión) bajo la CSP
    page.goto(f"{BASE}/login.html#registro", wait_until="networkidle")
    import secrets
    email = f"csp{secrets.token_hex(3)}@example.com"
    form = page.locator("#registerForm")
    form.locator("[name=name]").fill("Prueba CSP")
    form.locator("[name=email]").fill(email)
    form.locator("[name=password]").fill("Clave$egura123")
    form.locator("[name=confirm]").fill("Clave$egura123")
    form.locator("[type=submit]").click()
    page.wait_for_url("**/index.html*", timeout=30000)
    print("registro + login desde el navegador: OK ->", page.url)
    browser.close()

print("\nViolaciones de CSP / errores:", len(problems))
for pr in problems:
    print(" -", pr)
