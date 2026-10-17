# SETUP — Smart Search · Guía completa de instalación local

---

## Requisitos de software

| Programa           | Versión requerida    | Descarga                                  |
|--------------------|----------------------|-------------------------------------------|
| **Python**         | 3.12.x               | https://www.python.org/downloads/         |
| **PostgreSQL**     | 16.x o superior      | https://www.postgresql.org/download/      |
| **pip**            | incluido con Python  | —                                         |
| **Navegador**      | Chrome / Firefox     | —                                         |

> **No se necesita Node.js ni React.** El frontend es HTML/CSS/JS puro.

---

## Paso 1 — Instalar PostgreSQL

1. Descarga e instala **PostgreSQL** para tu sistema operativo.
2. Deja el puerto por defecto: **5432**.
3. Después de instalar, abre **pgAdmin** o la terminal **psql** y verifica que funcione.

---

## Paso 2 — Crear el usuario y la base de datos

El proyecto se conecta con estos datos (definidos en `main.py`):

| Dato           | Valor       |
|----------------|-------------|
| Host / puerto  | `localhost:5432` |
| Base de datos  | `news_dw`   |
| Usuario        | `myuser`    |
| Contraseña     | `admin`     |

Abre **psql** como superusuario (`postgres`) y ejecuta:

```sql
CREATE USER myuser WITH PASSWORD 'admin';
CREATE DATABASE news_dw OWNER myuser;
```

> ⚠️ Si usas otro usuario o contraseña, cámbialos en `main.py`, en el bloque `PostgreSQLConnection(...)`.

---

## Paso 3 — Crear las tablas y cargar los datos

Todo está en la carpeta `POSTGRES_BD/`:

| Archivo             | Qué hace                                                                 |
|---------------------|--------------------------------------------------------------------------|
| `create_tables.sql` | Crea los esquemas `dw` (tablas) y `mart` (vistas)                         |
| `load_data.sql`     | Importa los 6 CSV de `POSTGRES_BD/CSV/` en una sola transacción           |
| `CSV/*.csv`         | Datos: `dim_date`, `dim_category`, `dim_source`, `dim_article`, `fact_article`, `article_content` |

> ⚠️ `create_tables.sql` **borra y vuelve a crear** los esquemas `dw` y `mart` con todos sus datos.

`load_data.sql` usa rutas relativas, así que hay que ejecutarlo **desde la carpeta de los CSV**:

**Linux / Mac:**
```bash
cd POSTGRES_BD/CSV
psql -h localhost -U myuser -d news_dw -f ../create_tables.sql
psql -h localhost -U myuser -d news_dw -f ../load_data.sql
```

**Windows (PowerShell o CMD):**
```bat
cd POSTGRES_BD\CSV
psql -h localhost -U myuser -d news_dw -f ..\create_tables.sql
psql -h localhost -U myuser -d news_dw -f ..\load_data.sql
```

Al terminar, `load_data.sql` muestra el número de filas por tabla. Debe aparecer `fact_article` con **1870** filas.

Para comprobarlo manualmente:
```sql
SELECT count(*) FROM dw.fact_article;    -- 1870
SELECT count(*) FROM dw.dim_category;    -- 63
```

### Modelo de datos usado por la API

La API solo lee tres columnas, uniendo la tabla de hechos con dos dimensiones (`repository/article_repository.py`):

```sql
SELECT da.title, da.url, dc.category_name
FROM dw.fact_article fa
JOIN dw.dim_article  da ON da.article_key  = fa.article_key
JOIN dw.dim_category dc ON dc.category_key = fa.category_key
ORDER BY fa.article_key;
```

- `url` identifica cada artículo (es único).
- `category_name` es el tema que se muestra en las cards y en "Tendencias populares".

---

## Paso 4 — Configurar el entorno Python y las dependencias

Abre una terminal en la carpeta raíz del proyecto (`Frontend_equipo/`) y crea el entorno virtual:

```bash
python -m venv myenv
```

Actívalo:

```bash
# Windows:
myenv\Scripts\activate

# Linux / Mac (bash, zsh):
source myenv/bin/activate

# Linux (fish):
source myenv/bin/activate.fish
```

Instala las dependencias:

```bash
pip install -r requeriments.txt
```

> El archivo se llama `requeriments.txt` (con esa ortografía). Incluye `rank-bm25` (búsqueda BM25) y `sentence-transformers` (embeddings).

> **Nota:** `sentence-transformers` descarga el modelo `all-MiniLM-L6-v2` (~90 MB) la primera vez que arranca la API. Necesitas conexión a internet en ese primer arranque.

---

## Paso 5 — Iniciar el backend

Desde la carpeta raíz del proyecto, con el entorno activado:

```bash
uvicorn main:app --reload --port 8000
```

Si el servidor arrancó bien, verás algo así:

```
INFO:main:Artículos cargados: 1870
INFO:main:Modelo NLP entrenado y listo
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000
```

El primer arranque tarda más porque descarga el modelo de embeddings. Los siguientes tardan unos segundos.

Comprueba en el navegador:
- http://localhost:8000/health → `{"status":"ok","model_loaded":true,"articles_loaded":1870,...}`
- http://localhost:8000/docs → documentación interactiva de todos los endpoints

---

## Paso 6 — Abrir el frontend

En **otra terminal**, sirve la carpeta `frontend/`:

```bash
cd frontend
python -m http.server 5500
```

Y abre **http://localhost:5500/index.html**.

> También funciona abriendo `index.html` con doble clic, pero se recomienda el servidor local para evitar restricciones del navegador con archivos `file://`.

**Páginas:**
- `index.html` → buscador, slider de artículos destacados y tendencias populares (categorías de la BD)
- `articles.html` → listado completo con búsqueda, paginación y "Ver similares"

El frontend llama a la API en `http://localhost:8000` (constante `API` al inicio de `app.js`).

---

## Paso 7 — Ejecutar las pruebas (opcional)

```bash
python -m unittest discover -s tests -t . -v
```

No necesitan PostgreSQL ni internet: usan datos y embeddings simulados.

---

## Resumen de arranque diario

```bash
# Terminal 1 — backend
cd Frontend_equipo
myenv\Scripts\activate              # Windows
# source myenv/bin/activate         # Linux / Mac
uvicorn main:app --reload --port 8000

# Terminal 2 — frontend
cd Frontend_equipo/frontend
python -m http.server 5500

# Navegador
# http://localhost:5500/index.html
```

Para detener cualquiera de los dos servidores: `Ctrl+C` en su terminal.

---

## Solución de problemas comunes

| Error / síntoma                          | Causa probable                                  | Solución                                         |
|------------------------------------------|-------------------------------------------------|--------------------------------------------------|
| `could not connect to server`            | PostgreSQL no está corriendo                    | Inicia el servicio (Windows: Servicios; Linux: `sudo systemctl start postgresql`). Comprueba con `pg_isready -h localhost` |
| `password authentication failed`         | Usuario o contraseña distintos a los de `main.py` | Crea `myuser`/`admin` (Paso 2) o ajusta `main.py` |
| `relation "dw.fact_article" does not exist` | No se ejecutaron los scripts SQL             | Repite el Paso 3                                 |
| `could not open file "dim_date.csv"`     | `load_data.sql` se ejecutó desde otra carpeta   | Ejecútalo desde `POSTGRES_BD/CSV`                |
| `ModuleNotFoundError` (p. ej. `rank_bm25`) | Faltan dependencias o el entorno no está activo | Activa el entorno y `pip install -r requeriments.txt` |
| `uvicorn: command not found`             | Entorno virtual no activado                     | Activa el entorno (Paso 4)                       |
| `address already in use`                 | El puerto 8000 o 5500 ya está ocupado           | Cierra el servidor anterior o usa otro puerto    |
| `503 Modelo no disponible`               | La API aún está arrancando                      | Espera a ver "Modelo NLP entrenado y listo"      |
| "Backend no disponible" en la portada    | La API no está corriendo                        | Verifica http://localhost:8000/health            |

---

## Estructura del proyecto

```
Frontend_equipo/
├── main.py                          ← API FastAPI (credenciales de la BD)
├── requeriments.txt                 ← dependencias Python
├── database/
│   └── db_connection.py             ← conexión a PostgreSQL
├── repository/
│   └── article_repository.py        ← consulta de artículos
├── pipeline/
│   └── train.py                     ← entrenamiento del modelo
├── vectorizer/
│   └── NLPRecomender.py             ← motor BM25 + embeddings
├── tests/
│   └── test_nlp_recomender.py       ← pruebas unitarias
├── POSTGRES_BD/
│   ├── create_tables.sql            ← esquema news_dw (Paso 3)
│   ├── load_data.sql                ← carga de los CSV (Paso 3)
│   └── CSV/                         ← datos
├── frontend/
│   ├── index.html
│   ├── articles.html
│   ├── styles.css
│   ├── app.js
│   └── SETUP.md                     ← esta guía
├── mockup/                          ← diseños de la interfaz
└── myenv/                           ← entorno virtual (Paso 4, no se sube a git)
```
