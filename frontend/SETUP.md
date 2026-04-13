# SETUP — Smart Search · Guía completa de instalación local

---

## Requisitos de software

| Programa           | Versión requerida    | Descarga                                  |
|--------------------|----------------------|-------------------------------------------|
| **Python**         | 3.12.x               | https://www.python.org/downloads/         |
| **PostgreSQL**     | 16.x                 | https://www.postgresql.org/download/      |
| **pip**            | incluido con Python  | —                                         |
| **Navegador**      | Chrome / Firefox     | —                                         |

> **No se necesita Node.js ni React.** El frontend es HTML/CSS/JS puro que se abre directamente en el navegador.

---

## Paso 1 — Instalar PostgreSQL

1. Descarga e instala **PostgreSQL 16** para tu sistema operativo.
2. Durante la instalación, cuando pida contraseña para el usuario **postgres**, escribe: `root`
3. Deja el puerto por defecto: **5432**
4. Después de instalar, abre **pgAdmin** o la terminal **psql** y verifica que funcione.

> ⚠️ Si instalaste PostgreSQL con otro usuario o contraseña, edita el archivo  
> `Frontend_equipo-main/main.py` línea donde dice `user="postgres", password="root"` y ajústalo.

---

## Paso 2 — Crear la base de datos y las tablas

Abre **psql** o pgAdmin y ejecuta:

```sql
-- 1. Crear la base de datos
CREATE DATABASE mediumdb;

-- 2. Conectarte a ella
\c mediumdb
```

Luego ejecuta el script de creación de tablas que está en la carpeta `postgresql/`:

```sql
-- Contenido de postgresql/tablas.sql

CREATE TABLE dim_date (
    date_key SERIAL PRIMARY KEY,
    full_date TIMESTAMP,
    year INT,
    quarter INT,
    month INT,
    month_name VARCHAR(20),
    day INT,
    day_of_week VARCHAR(20),
    week_of_year INT
);

CREATE TABLE dim_feed_tag (
    feed_tag_key SERIAL PRIMARY KEY,
    feed_tag_name TEXT
);

CREATE TABLE fact_articles (
    article_key SERIAL PRIMARY KEY,
    article_id TEXT UNIQUE,
    title TEXT
);
```

---

## Paso 3 — Importar los datos CSV

En psql (conectado a mediumdb), ejecuta **un comando por cada tabla**.  
Reemplaza `C:/ruta/a/tu/proyecto` con la ubicación real de la carpeta `csv/`:

```sql
-- Importar dim_date
\copy dim_date FROM 'C:/ruta/a/tu/proyecto/csv/dim_date.csv' DELIMITER ',' CSV HEADER;

-- Importar dim_feed_tag
\copy dim_feed_tag FROM 'C:/ruta/a/tu/proyecto/csv/dim_feed_tag.csv' DELIMITER ',' CSV HEADER;

-- Importar fact_articles
\copy fact_articles FROM 'C:/ruta/a/tu/proyecto/csv/fact_articles.csv' DELIMITER ',' CSV HEADER;
```

**Ejemplo en Windows:**
```sql
\copy fact_articles FROM 'C:/Users/TuNombre/Desktop/Frontend_equipo-main/csv/fact_articles.csv' DELIMITER ',' CSV HEADER;
```

**Ejemplo en Mac/Linux:**
```sql
\copy fact_articles FROM '/home/usuario/Frontend_equipo-main/csv/fact_articles.csv' DELIMITER ',' CSV HEADER;
```

Verifica que los datos se cargaron:
```sql
SELECT COUNT(*) FROM fact_articles;   -- debe mostrar miles de filas
SELECT COUNT(*) FROM dim_feed_tag;
```

---

## Paso 4 — Corrección necesaria en main.py (feed_tag_name)

El archivo `main.py` tiene `DISPLAY_COLUMNS = ["title", "article_id"]`.  
Esto hace que el API **no devuelva las etiquetas** de cada artículo.

**Abre `Frontend_equipo-main/main.py` y cambia la línea 14:**

```python
# ANTES:
DISPLAY_COLUMNS = ["title", "article_id"]

# DESPUÉS:
DISPLAY_COLUMNS = ["title", "article_id", "feed_tag_name"]
```

Esta es la única modificación necesaria al backend.

---

## Paso 5 — Configurar el entorno Python y las dependencias

Abre una terminal en la carpeta `Frontend_equipo-main/`:

```bash
cd Frontend_equipo-main
```

Crea y activa el entorno virtual:

```bash
# Crear entorno
python -m venv env

# Activar en Windows:
env\Scripts\activate

# Activar en Mac/Linux:
source env/bin/activate
```

Instala las dependencias:

```bash
pip install -r requeriments.txt
```

Si la instalación falla por alguna librería, instálalas manualmente:

```bash
pip install fastapi==0.111.0
pip install uvicorn==0.29.0
pip install psycopg2-binary==2.9.9
pip install pandas==2.2.2
pip install scikit-learn==1.4.2
pip install sentence-transformers==2.7.0
pip install numpy==1.26.4
pip install pydantic==2.7.1
```

> **Nota:** `sentence-transformers` descarga el modelo `all-MiniLM-L6-v2` (~90MB) la primera vez que se ejecuta. Asegúrate de tener conexión a internet en el primer arranque.

---

## Paso 6 — Iniciar el backend

**Importante:** Debes ejecutar uvicorn **desde dentro** de la carpeta `Frontend_equipo-main/`, no desde una carpeta superior.

```bash
# Asegúrate de estar en la carpeta correcta:
cd Frontend_equipo-main

# Con el entorno activado:
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

> ⚠️ El README dice `uvicorn src.main:app` — eso es incorrecto porque no existe carpeta `src/`.  
> El comando correcto es `uvicorn main:app --reload`.

Si el servidor arrancó bien, verás algo así:

```
INFO:     Artículos cargados: 15234
INFO:     Modelo NLP entrenado y listo
INFO:     Uvicorn running on http://0.0.0.0:8000
```

El **entrenamiento del modelo tarda entre 1 y 3 minutos** la primera vez (descarga embeddings y vectoriza todos los artículos). Espera hasta ver "Modelo NLP entrenado y listo".

Verifica en el navegador: http://localhost:8000/health  
Debe responder: `{"status":"ok","model_loaded":true,...}`

---

## Paso 7 — Abrir el frontend

El frontend **no necesita servidor web**. Abre el archivo directamente:

1. Navega a la carpeta `frontend/` (donde están los archivos HTML)
2. Haz doble clic en `index.html`  
   — O abre tu navegador y arrastra el archivo a él

**Páginas:**
- `index.html` → Página principal con buscador y slider de artículos
- `articles.html` → Listado completo con búsqueda, paginación y "Ver similares"

---

## Resumen de arranque diario

Una vez todo instalado, cada vez que quieras usar el proyecto:

```bash
# 1. Terminal → carpeta del proyecto
cd Frontend_equipo-main

# 2. Activar entorno virtual
env\Scripts\activate          # Windows
# source env/bin/activate     # Mac/Linux

# 3. Iniciar backend
uvicorn main:app --reload

# 4. Abrir index.html en el navegador
```

---

## Solución de problemas comunes

| Error                                    | Causa probable                          | Solución                                         |
|------------------------------------------|-----------------------------------------|--------------------------------------------------|
| `could not connect to server`            | PostgreSQL no está corriendo            | Inicia el servicio PostgreSQL desde el panel de control o `pg_ctl start` |
| `password authentication failed`         | Contraseña incorrecta en main.py        | Cambia `password="root"` por la contraseña que usaste al instalar |
| `ModuleNotFoundError`                    | Falta instalar dependencias             | `pip install -r requeriments.txt`               |
| `uvicorn: command not found`             | Entorno virtual no activado             | Activa con `env\Scripts\activate`               |
| `503 Modelo no disponible`               | El modelo aún está entrenando           | Espera 1-3 min hasta ver "Modelo NLP entrenado" en la terminal |
| Frontend sin artículos (fondo vacío)     | Backend no corriendo o CORS bloqueado   | Verifica http://localhost:8000/health           |
| Tags no aparecen en las cards            | DISPLAY_COLUMNS sin feed_tag_name       | Aplica la corrección del Paso 4                 |

---

## Estructura final del proyecto

```
Frontend_equipo-main/
├── main.py                 ← API FastAPI (modificar DISPLAY_COLUMNS)
├── requeriments.txt        ← dependencias Python
├── database/
│   └── db_connection.py
├── repository/
│   └── article_repository.py
├── pipeline/
│   └── train.py
├── vectorizer/
│   └── NLPRecomender.py
├── postgresql/
│   └── tablas.sql          ← ejecutar en psql
├── csv/
│   ├── dim_date.csv
│   ├── dim_feed_tag.csv
│   └── fact_articles.csv   ← importar con \copy
└── env/                    ← entorno virtual (creado en Paso 5)

frontend/                   ← carpeta del frontend (abrir en navegador)
├── index.html
├── articles.html
├── styles.css
└── app.js
```
