# Informe de seguridad — DATARA (SmartSearch API + frontend)

| | |
|---|---|
| **Fecha** | 4 de noviembre de 2026 |
| **Versión analizada** | commit `b22a184` (rama `main`) y correcciones de este informe |
| **Guía de referencia** | OWASP Top 10:2025 · OWASP ASVS 4.0 (nivel 1) como lista de control |
| **Resultado** | 8 hallazgos: 7 corregidos, 1 (H2) mitigado parcialmente con acciones pendientes en AWS |

---

## 1. Alcance y autorización

**Dentro del alcance**

- Código fuente del repositorio: API FastAPI (`main.py`, `auth/`, `repository/`, `database/`, `middleware/`),
  frontend estático (`frontend/`) y esquema SQL (`POSTGRES_BD/`).
- Dependencias de Python (`requirements-api.txt`, `requeriments.txt`).
- Configuración de despliegue (Dockerfile, definición de tarea de ECS, distribución de CloudFront).
- Pruebas dinámicas **solo en el equipo local** del desarrollador: API en `127.0.0.1` y PostgreSQL en Docker
  con los datos del repositorio.

**Fuera del alcance**

- El entorno desplegado en AWS (CloudFront, ALB, ECS, RDS, SageMaker): **no se envió ninguna petición de
  prueba**. Los hallazgos de AWS salen de revisar los archivos de configuración.
- El modelo Qwen/SageMaker y el pipeline de extracción de noticias.
- Pruebas de denegación de servicio por volumen e ingeniería social.

**Autorización:** las pruebas se hicieron sobre código y sistemas propios del equipo, en local. Antes de
probar el entorno de AWS hay que completar y firmar el [Anexo A](#anexo-a--autorización-de-pruebas).

## 2. Metodología y herramientas

| Actividad | Herramienta | Resultado |
|---|---|---|
| Análisis estático (SAST) | Bandit 1.9.4 sobre todo el backend (1171 líneas) + revisión manual de backend y frontend | [antes](evidencias/bandit_antes.txt) · [después](evidencias/bandit_despues.txt) |
| Análisis de dependencias (SCA) | pip-audit (base de datos PyPA/OSV) sobre las versiones fijadas y el árbol completo de dependencias transitivas | [antes](evidencias/pip_audit_antes.txt) · [después](evidencias/pip_audit_despues.txt) |
| Pruebas dinámicas (DAST) | Scripts en `pruebas/` (httpx + Chromium headless/Playwright) contra la app en local | [resultados](evidencias/resultados_pruebas.txt): 42/42, 11/11, 0 violaciones de CSP |
| Revisión de configuración | Revisión manual de Dockerfile, ECS y CloudFront | Hallazgos H2, H5–H7 |

Severidad: **Alta**: compromete datos o credenciales sin condiciones especiales. **Media**: necesita
condiciones adicionales o tiene un impacto limitado. **Baja**: refuerzo o exposición de información menor.

## 3. Resumen de hallazgos

| ID | Hallazgo | OWASP 2025 | Severidad | Estado |
|---|---|---|---|---|
| H1 | Dependencias con vulnerabilidades conocidas | A03 Fallos en la cadena de suministro | **Alta** | ✅ Corregido |
| H2 | Tramo CloudFront → ALB por HTTP; el ALB se puede llamar directamente | A04 Fallos criptográficos / A02 | **Alta** | 🟡 Mitigado (falta aplicar en AWS) |
| H3 | El login permite saber qué correos tienen cuenta | A07 Fallos de autenticación | Media | ✅ Corregido |
| H4 | Sin límite de peticiones (fuerza bruta, abuso de correo y de SageMaker) | A07 / A06 Diseño inseguro | Media | ✅ Corregido |
| H5 | Faltan cabeceras de seguridad (CSP, HSTS, anti-clickjacking) | A02 Configuración incorrecta | Media | ✅ Corregido y publicado en CloudFront |
| H6 | CORS abierto a cualquier origen (`*`) en producción | A02 Configuración incorrecta | Baja | ✅ Corregido |
| H7 | Swagger, OpenAPI y modo de ejecución expuestos en producción | A02 Configuración incorrecta | Baja | ✅ Corregido |
| H8 | Parámetros sin tope de tamaño (`top_n`, `limit`, cuerpos de login) | A06 Diseño inseguro / A10 | Baja | ✅ Corregido |

Falsos positivos descartados: los 3 avisos de Bandit (sección 5).

---

## 4. Detalle de los hallazgos

### H1 — Dependencias con vulnerabilidades conocidas · Alta · ✅ Corregido

**Descripción.** pip-audit encontró 53 avisos en 7 paquetes:

| Paquete | Versión anterior | Avisos | Versión nueva |
|---|---|---|---|
| starlette (base de FastAPI) | 0.52.1 | 5 | 1.10.0 |
| transformers | 4.57.6 | 7 | 5.22.1 |
| sentence-transformers | 2.7.0 | 1 | 6.2.0 |
| urllib3 | 2.6.3 | 5 | 2.8.0 |
| requests | 2.32.5 | 1 | 2.34.2 |
| soupsieve | 2.8.3 | 4 | 4.0.1 |
| fastapi / uvicorn / pydantic | 0.135.1 / 0.42.0 / 2.12.5 | — (se suben para admitir starlette 1.x) | 0.162.0 / 0.54.0 / 2.14.2 |

**Corrección.** Versiones nuevas fijadas en `requirements-api.txt` y `requeriments.txt`. El conjunto completo
se resolvió con `uv pip compile` para que no haya conflictos entre dependencias.

**Verificación.** pip-audit da *"No known vulnerabilities found"* para la imagen de la API, su árbol completo de
dependencias transitivas y torch 2.14.1. Se comprobó que la app sigue funcionando: con los paquetes nuevos
arranca, entrena el modelo con los 1870 artículos y responde a búsqueda, recomendaciones, artículos y
categorías (primeras 5 pruebas de `pruebas_api_local.py`).

**Riesgo aceptado.** `deep-translator 1.11.4` aparece en PYSEC-2022-252, que corresponde al secuestro de la
cuenta del proyecto en PyPI en 2022. El aviso no indica ninguna versión corregida, así que marca todas las
versiones desde la 1.8.5. Ningún archivo `.py` del repositorio importa este paquete y **no se instala en la
imagen de la API**: solo está en `requeriments.txt` para los scripts de extracción. Recomendación: quitarlo si
esos scripts ya no se usan.

### H2 — Tramo CloudFront → ALB sin cifrar · Alta · 🟡 Mitigado, falta aplicar en AWS

**Descripción.** El navegador se conecta a CloudFront por HTTPS, pero CloudFront reenvía `/api/*` al ALB
con `OriginProtocolPolicy: http-only`. Las contraseñas, los tokens de sesión y los de recuperación viajan
sin cifrar en ese tramo. Además, si el grupo de seguridad del ALB admite tráfico de fuera de CloudFront,
cualquiera puede llamar a la API directamente por HTTP, saltándose CloudFront y las cabeceras que pone.

**Corrección aplicada (código).**
- `middleware/http_security.py` → `OriginVerifyMiddleware`: con `ORIGIN_VERIFY_SECRET` definido, la API
  rechaza con **403** cualquier petición que no traiga el encabezado secreto `X-Origin-Verify`, que solo
  CloudFront añade. `/health` queda exento para el health check del ALB.
- `deploy/harden_cloudfront.sh` (solo en local, no se sube): crea el secreto en Secrets Manager y configura
  CloudFront para enviarlo.

**Verificación.** `pruebas_modo_aws.py`: una petición sin el encabezado o con un valor incorrecto recibe 403;
con el encabezado correcto pasa.

**Aplicado en AWS (4/11/2026).** CloudFront envía `X-Origin-Verify` y la tarea de ECS (`mi-app:7`) exige
`ORIGIN_VERIFY_SECRET`. Una petición directa al ALB que no pase por CloudFront recibe 403.

**Pendiente (infraestructura).**
1. ~~Ejecutar `deploy/harden_cloudfront.sh` y añadir `ORIGIN_VERIFY_SECRET` a la tarea de ECS.~~ Hecho.
2. Restringir el grupo de seguridad del ALB a la *managed prefix list*
   `com.amazonaws.global.cloudfront.origin-facing`. **Comprobado el 4/11/2026: hoy admite el puerto 80 desde
   `0.0.0.0/0`**, es decir, desde cualquier IP. El grupo de las tareas sí está bien: el puerto 8000 solo admite
   tráfico desde el ALB.
3. **Corrección completa:** cifrar el tramo. CloudFront solo acepta un certificado del origen que
   coincida con su nombre, y no se puede emitir un certificado ACM para el DNS por defecto del ALB
   (`*.elb.amazonaws.com`). Hace falta un dominio propio: registrarlo en Route 53, emitir en ACM un
   certificado para `api.<dominio>`, añadir al ALB un listener HTTPS:443 y poner en CloudFront el origen
   `api.<dominio>` con `OriginProtocolPolicy: https-only`.

**Riesgo residual aceptado** (el equipo pospone el paso 3 por no tener dominio propio). El tráfico entre CloudFront y el ALB, en la misma
región, va por la red de AWS, pero sin cifrar.

### H3 — Se podía saber qué correos tienen cuenta · Media · ✅ Corregido

**Descripción.** Con un correo registrado y una contraseña incorrecta, `/auth/login` respondía
*"…Te quedan 4 intentos antes del bloqueo"*. Con un correo inexistente solo decía *"Correo o contraseña
incorrectos"*. Esa diferencia permitía averiguar qué correos están registrados, y anulaba la protección
por tiempo que ya existía (`burn_password_check`).

**Corrección.** `auth/router.py`: los dos casos devuelven exactamente el mismo `401` con
*"Correo o contraseña incorrectos."*. El bloqueo tras 5 intentos sigue funcionando.

**Verificación.** `pruebas_api_local.py`: misma respuesta y mismo código en los dos casos; el 5.º intento
fallido devuelve 423.

**Riesgo aceptado.** `/auth/register` responde 409 si el correo ya existe, porque así lo exige el requisito de
que un correo solo se registre una vez. Un atacante también podría notar el bloqueo (423) tras 5 intentos.
Ambos casos quedan limitados por el rate limiting de H4: 5 registros cada 15 min y 10 logins por minuto
por IP.

### H4 — Sin límite de peticiones · Media · ✅ Corregido

**Descripción.** Ningún endpoint limitaba el número de peticiones. Eso permitía:
- probar contraseñas contra muchas cuentas (el bloqueo es por cuenta, no por atacante);
- registrar cuentas en masa;
- enviar correos de recuperación de forma abusiva;
- generar gasto en SageMaker llamando sin parar a `/teaser`.

**Corrección.** Nuevo `middleware/rate_limit.py`: ventana deslizante por IP que responde **429** con
`Retry-After`.

| Grupo | Límite por IP |
|---|---|
| `/auth/login` | 10 / minuto |
| `/auth/register` | 5 / 15 minutos |
| `/auth/forgot-password` | 5 / 15 minutos (además de 1 correo por cuenta cada 60 s) |
| `/auth/reset-password` | 10 / 15 minutos |
| `/auth/me`, `/auth/logout` | 60 / minuto |
| `/articles/{url}/teaser` (SageMaker) | 10 / minuto |
| `/search`, `/recommend`, `/related` | 60 / minuto |
| `/articles`, `/categories` | 120 / minuto |

**Detalle importante.** El contenedor arranca uvicorn con `--forwarded-allow-ips "*"`, así que
`request.client.host` toma el **primer** valor de `X-Forwarded-For`, que el cliente puede falsificar. Por eso
el limitador cuenta `TRUSTED_PROXY_HOPS` saltos desde la derecha. En AWS el valor es 2 (CloudFront + ALB).

**Verificación.** `pruebas_api_local.py`: la 11.ª petición de login, el 6.º registro, el 6.º correo de
recuperación y la 61.ª búsqueda reciben 429, y otra IP no se ve afectada. `pruebas_modo_aws.py`: un
`X-Forwarded-For` falsificado por el cliente se ignora.

**Limitación.** El contador vive en memoria: con varias tareas de ECS el límite es por tarea, y se reinicia
al redesplegar. Para un límite global se recomienda AWS WAF con una regla *rate-based* en CloudFront.

### H5 — Faltaban cabeceras de seguridad · Media · ✅ Corregido y publicado

**Descripción.** Ni la API ni el frontend enviaban CSP, HSTS, `X-Frame-Options` ni `X-Content-Type-Options`.
Esto tiene más peso porque el token de sesión se guarda en `localStorage`: si alguna vez se colara un XSS,
podría leerlo.

**Corrección.**
- **API**: `SecurityHeadersMiddleware` añade `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
  `Referrer-Policy: no-referrer`, una CSP `default-src 'none'` y `Cache-Control: no-store` en `/auth/*`.
- **Frontend**: `deploy/cloudfront-security-headers.json` es una *Response Headers Policy* con HSTS (1 año),
  `nosniff`, `DENY`, `Permissions-Policy` y una CSP estricta, entre otras directivas:
  `script-src 'self'` (sin scripts inline ni `eval`), `connect-src 'self'` y `frame-ancestors 'none'`.
  `harden_cloudfront.sh` la crea y la asigna a la distribución.

**Verificación.** Para la API, `pruebas_api_local.py`. Para el frontend, `pruebas_csp_navegador.py` sirve las
4 páginas con la misma CSP y las recorre con Chromium: tarjetas, búsqueda, fuente de Google y el registro +
login completos funcionan con **0 violaciones de CSP**. En producción (4/11/2026) CloudFront ya envía todas las
cabeceras, y Chromium sobre las 4 páginas reales da 0 violaciones
([evidencia](evidencias/cabeceras_produccion.txt)).

**Riesgo aceptado.** El token sigue en `localStorage`. La alternativa más segura, una cookie `HttpOnly` +
`SameSite`, obliga a rediseñar la sesión y a añadir protección CSRF. Con la CSP estricta y el escape de
toda la salida (`esc()` antes de cada `innerHTML`), el riesgo de XSS es bajo.

### H6 — CORS abierto (`*`) · Baja · ✅ Corregido

- La definición de tarea de ECS define `CORS_ORIGINS` con el dominio de CloudFront.
- La API registra una advertencia si arranca fuera de local con `*`.
- `allow_headers` pasa de `*` a `Authorization, Content-Type`.

Verificado en `pruebas_modo_aws.py`: un origen ajeno no recibe `Access-Control-Allow-Origin`. El impacto era
bajo porque la sesión va en el encabezado `Authorization` y no en cookies.

### H7 — Información expuesta en producción · Baja · ✅ Corregido

- `/docs`, `/redoc` y `/openapi.json` solo se publican con `APP_MODE=local` o con `ENABLE_DOCS=true`.
- `/health` deja de mostrar el modo de ejecución.

Verificado en `pruebas_modo_aws.py` (404 en modo AWS).

### H8 — Parámetros sin tope · Baja · ✅ Corregido

**Antes:** se podía pedir `top_n=1000000` o `limit=1000000`, o mandar una contraseña de varios MB, que
Argon2 tendría que procesar.

**Ahora:**

| Parámetro | Rango permitido |
|---|---|
| `query` | ≤ 500 caracteres |
| `top_n` de búsqueda | 1–50 |
| `top_n` de recomendaciones | 1–20 |
| `limit` de artículos | 1–100 |
| `offset` | ≥ 0 |
| `limit` de categorías | 1–50 |
| Campos de las cuentas | Topes de tamaño; contraseñas ≤ 1024 caracteres |

Cualquier valor fuera de rango devuelve **422**. Verificado en `pruebas_api_local.py`.

---

## 5. Controles revisados que ya cumplían

| Control | Evidencia |
|---|---|
| **Inyección SQL** | Todas las consultas usan parámetros de psycopg2 (`%s`, `%(x)s`), nunca concatenación. Probado con `' OR '1'='1`, `DROP TABLE` y `UNION SELECT` en la URL y en el login: 404/401 y la tabla queda intacta. No hay NoSQL. |
| **XSS** | El frontend escapa todo dato dinámico con `esc()` antes de usar `innerHTML`, y los parámetros de URL con `encodeURIComponent`. No hay `eval` ni scripts inline. |
| **Control de acceso** | Los artículos son públicos por diseño. `/auth/me` y `/auth/logout` obtienen el usuario del token, nunca de un ID enviado por el cliente, así que no hay IDOR. No existen funciones de administración expuestas. |
| **Contraseñas** | Argon2id. Política: 8–128 caracteres con número, mayúscula y carácter especial. |
| **Datos personales** | Correo y nombre cifrados con Fernet (AES-128-CBC + HMAC). Búsqueda por correo mediante HMAC-SHA256. Claves derivadas con HKDF. |
| **Sesiones** | Token aleatorio de 256 bits; en la base solo se guarda su SHA-256. Expiración por inactividad (30 min) y máxima (12 h). Una sesión por cuenta. Probado: un token inventado, uno reutilizado tras logout o uno reemplazado por otra sesión reciben 401. |
| **Recuperación de contraseña** | Token de un solo uso, válido 30 min. Va en el fragmento de la URL (`#reset=`), así que no llega a logs ni a `Referer`. Respuesta idéntica exista o no el correo. Probado: un token falso recibe 400. |
| **Bloqueo** | 5 intentos fallidos bloquean la cuenta 15 min, evaluado de forma atómica en PostgreSQL. Probado: 423, incluso con la contraseña correcta. |
| **Secretos** | `DB_PASSWORD` y `AUTH_SECRET_KEY` vienen de Secrets Manager. La API no arranca en AWS sin ellos y rechaza la clave de desarrollo. |
| **Errores** | Los 500 devuelven mensajes genéricos y el detalle va solo al log. Los logs no registran contraseñas ni tokens. |
| **Base de datos en tránsito** | `DB_SSLMODE=require` hacia RDS. |
| **Contenedor** | Se ejecuta con el usuario `app` (uid 1000), no como root. |

**Falsos positivos de Bandit**

| Aviso | Por qué no es vulnerabilidad | Tratamiento |
|---|---|---|
| B105 `DEV_SECRET_KEY` | `setup()` la rechaza fuera de `APP_MODE=local` | `# nosec B105` con justificación |
| B107 `password="admin"` | Valor por defecto del Postgres local; en AWS `check_db_env()` exige las variables | `# nosec B107` con justificación |
| B608 f-string SQL | Solo interpolaba una constante | Se escribieron las columnas directamente en el SQL (el aviso desaparece sin silenciarlo) |

## 6. Acciones pendientes del equipo

| # | Acción | Hallazgo | Responsable | Estado |
|---|---|---|---|---|
| 1 | Construir y subir la nueva imagen. Antes de subirla se probó en local con `APP_MODE=aws`: health, búsqueda, `/docs`→404, topes y cabeceras correctos. | H1, H3, H4, H6–H8 | | ☑ 4/11/2026 · imagen `mi-app:a4160df` (también `:latest`), commit `a4160df` |
| 2 | Registrar la nueva definición de tarea (`CORS_ORIGINS`, `TRUSTED_PROXY_HOPS=2`) y asignarla a `mi-servicio` | H4, H6 | | ☑ 4/11/2026 · revisión `mi-app:6`; el servicio sigue pausado (0 tareas) y la usará al reactivarse |
| 3 | `CLOUDFRONT_DISTRIBUTION_ID=<id> bash deploy/harden_cloudfront.sh` | H2, H5 | | ☑ 4/11/2026 · política de cabeceras en ambos comportamientos; CloudFront envía `X-Origin-Verify` al ALB; secreto `smartsearch/origin-verify` creado |
| 4 | Cuando CloudFront esté *Deployed*: añadir `ORIGIN_VERIFY_SECRET` a la tarea, dar `GetSecretValue` al rol de ejecución y redesplegar. **No hacerlo antes del paso 3**: la API rechazaría con 403 todas las peticiones | H2 | | ☑ 4/11/2026 · revisión `mi-app:7` con el secreto; permiso `ReadOriginVerifySecret` en el rol de ejecución; se comprobó que el valor coincide con el que envía CloudFront |
| 5 | Restringir el grupo de seguridad del ALB (hoy `0.0.0.0/0:80`) a la prefix list de CloudFront: primero añadir la regla nueva y luego quitar la abierta | H2 | | 🟡 4/11/2026 · regla de la prefix list añadida; **la regla `0.0.0.0/0:80` sigue activa** hasta que el equipo decida quitarla |
| 5b | Activar `scanOnPush` en el repositorio de ECR (hoy la imagen no tiene escaneo) | H1 | | ⏸ Descartado por el equipo; las dependencias se auditan con pip-audit |
| 6 | Dominio propio + certificado ACM + HTTPS de CloudFront al ALB | H2 | | ⏸ Pospuesto: el proyecto no tiene dominio propio (riesgo residual aceptado, ver H2) |
| 7 | Firmar el Anexo A y repetir las pruebas contra AWS (incluido un escaneo OWASP ZAP *baseline*) | — | | ☐ |
| 8 | Opcional: AWS WAF con regla *rate-based*; quitar `deep-translator` si no se usa | H1, H4 | | ☐ |

**Comprobación tras desplegar** (los resultados esperados están verificados en local):

```bash
curl -sI https://<dominio>/            | grep -iE "strict-transport|content-security|x-frame"
curl -s  https://<dominio>/api/docs    # → 404
curl -s  http://<dns-del-alb>/api/articles   # → 403 o sin respuesta (no pasa por CloudFront)
```

## 7. Cómo reproducir las pruebas

```bash
# 1. Base de datos de prueba con los datos del repositorio
docker run -d --rm --name datara-sec-test -e POSTGRES_USER=myuser -e POSTGRES_PASSWORD=admin \
  -e POSTGRES_DB=news_dw -p 127.0.0.1:55432:5432 -v "$PWD/POSTGRES_BD:/sql:ro" postgres:18
docker exec -w /sql     datara-sec-test psql -U myuser -d news_dw -f create_tables.sql
docker exec -w /sql/CSV datara-sec-test psql -U myuser -d news_dw -f /sql/load_data.sql

# 2. API con las dependencias actualizadas
DB_PORT=55432 APP_MODE=local uvicorn main:app --host 127.0.0.1 --port 58000

# 3. Pruebas (en otra terminal; requieren httpx y, la de navegador, playwright)
python seguridad/pruebas/pruebas_api_local.py
python seguridad/pruebas/pruebas_modo_aws.py "$PWD"
python seguridad/pruebas/servidor_csp.py frontend deploy/cloudfront-security-headers.json 58080 &
python seguridad/pruebas/pruebas_csp_navegador.py

# Análisis estático y de dependencias
uvx bandit -r main.py auth database repository pipeline vectorizer teaser middleware
uvx pip-audit -r requirements-api.txt --no-deps --disable-pip
```

`pruebas_api_local.py` crea cuentas de prueba y bloquea una a propósito: **úsalo solo contra la base de
prueba**, nunca contra RDS.

---

## Anexo A — Autorización de pruebas

| Campo | Valor |
|---|---|
| Sistema | DATARA / SmartSearch |
| Entornos autorizados | ☐ Local (equipo de desarrollo) ☐ AWS (cuenta del proyecto, región us-east-1) |
| Pruebas autorizadas | ☐ SAST ☐ Dependencias ☐ DAST manual/automatizado ☐ Escaneo OWASP ZAP baseline |
| Excluido | Denegación de servicio por volumen, ingeniería social, sistemas de terceros (SageMaker más allá del uso normal, SES) |
| Ventana de pruebas | del ____ al ____ |
| Responsable de las pruebas | |
| Autoriza (propietario del sistema / docente) | Nombre: ____________ Firma: ____________ Fecha: ________ |
