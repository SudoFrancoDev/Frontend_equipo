import logging
import os
from contextlib import asynccontextmanager


import pandas as pd
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from database.db_connection import PostgreSQLConnection
from repository.article_repository import ArticleRepository
from pipeline.train import train_model, show_recommendations
from vectorizer.NLPRecomender import NLPRecomender
from teaser.teaser_model import TeaserModel, InvalidInputError, TeaserGenerationError
from auth import router as auth
from middleware.http_security import OriginVerifyMiddleware, SecurityHeadersMiddleware, origin_verify_secret
from middleware.rate_limit import rate_limit

# ─────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DISPLAY_COLUMNS = ["title", "url", "category_name"]

# ─────────────────────────────────────────────
# Configuración (variables de entorno)
# Los valores por defecto son los del entorno local; en AWS los define la tarea de ECS.
# ─────────────────────────────────────────────
DB_CONFIG = {
    "host":     os.getenv("DB_HOST", "localhost"),
    "port":     int(os.getenv("DB_PORT", "5432")),
    "database": os.getenv("DB_NAME", "news_dw"),
    "user":     os.getenv("DB_USER", "myuser"),
    "password": os.getenv("DB_PASSWORD", "admin"),
    "sslmode":  os.getenv("DB_SSLMODE", "prefer"),   # RDS PostgreSQL 18 exige SSL: "require"
}

# Prefijo de las rutas: "" en local, "/api" detrás de CloudFront (web y API en el mismo dominio)
API_PREFIX = os.getenv("API_PREFIX", "").rstrip("/")

# Orígenes permitidos por CORS, separados por comas
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]

APP_MODE = os.getenv("APP_MODE", "local")

# Swagger (/docs) y el esquema OpenAPI solo se publican en local, salvo ENABLE_DOCS=true
ENABLE_DOCS = APP_MODE == "local" or os.getenv("ENABLE_DOCS", "").lower() == "true"

# Variables que la tarea de ECS debe definir: fuera de local no se usan los valores por defecto
REQUIRED_DB_ENV = ["DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD", "DB_SSLMODE"]


def check_db_env():
    """
    En AWS falla al arrancar si falta alguna variable de la BD, en vez de intentar conectar a localhost.
    """
    if APP_MODE == "local":
        return
    missing = [name for name in REQUIRED_DB_ENV if not os.getenv(name, "").strip()]
    if missing:
        raise RuntimeError(f"Faltan variables de entorno de la base de datos: {', '.join(missing)}")

# ─────────────────────────────────────────────
# Estado global (modelo + datos)
# ─────────────────────────────────────────────
model: NLPRecomender = None
df: pd.DataFrame = None
repo: ArticleRepository = None
teaser_model: TeaserModel = None

# ─────────────────────────────────────────────
# Startup / Shutdown
# ─────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    global model, df, repo, teaser_model

    # ── Conectar a PostgreSQL (local o RDS) ────
    check_db_env()
    # Se registra la configuración sin la contraseña
    logger.info(
        f"Conectando a PostgreSQL {DB_CONFIG['user']}@{DB_CONFIG['host']}:{DB_CONFIG['port']}/"
        f"{DB_CONFIG['database']} (sslmode={DB_CONFIG['sslmode']}, modo {APP_MODE})"
    )
    db = PostgreSQLConnection(**DB_CONFIG)
    db.connect()
    logger.info("Conectado a PostgreSQL")

    # ── Cargar datos y entrenar modelo ─────────
    repo = ArticleRepository(db)
    df = repo.get_articles()
    logger.info(f"Artículos cargados: {len(df)}")

    model = train_model(df)
    logger.info("Modelo NLP entrenado y listo")

    # ── Cuentas de usuario (opcional para buscar) ──
    auth.setup(db)

    # ── Modelo de teaser (SageMaker) ───────────
    endpoint_name = os.getenv("TEASER_ENDPOINT_NAME")
    if endpoint_name:
        teaser_model = TeaserModel(endpoint_name, region_name=os.getenv("AWS_REGION", "us-east-1"))
        logger.info(f"Teaser habilitado con el endpoint '{endpoint_name}'")
    else:
        logger.warning("TEASER_ENDPOINT_NAME no definido: /articles/{url}/teaser no estará disponible")

    yield  # API corriendo

    # ── Cerrar conexión al apagar ──────────────
    db.close()
    logger.info("Conexión a BD cerrada")


# ─────────────────────────────────────────────
# App
# ─────────────────────────────────────────────
app = FastAPI(
    title="SmartSearch API",
    description="API basada en PostgreSQL + NLPRecomender (BM25 + embeddings) + teaser en SageMaker + cuentas de usuario",
    version="1.2.0",
    lifespan=lifespan,
    docs_url=f"{API_PREFIX}/docs" if ENABLE_DOCS else None,
    redoc_url=f"{API_PREFIX}/redoc" if ENABLE_DOCS else None,
    openapi_url=f"{API_PREFIX}/openapi.json" if ENABLE_DOCS else None,
)

if "*" in CORS_ORIGINS and APP_MODE != "local":
    logger.warning("CORS_ORIGINS='*' fuera de local: define el dominio de CloudFront")

# El último middleware añadido es el más externo: CORS → verificación de origen → cabeceras
app.add_middleware(
    SecurityHeadersMiddleware,
    api_prefix=API_PREFIX,
    docs_paths=(f"{API_PREFIX}/docs", f"{API_PREFIX}/redoc") if ENABLE_DOCS else (),
)
if origin_verify_secret():
    app.add_middleware(OriginVerifyMiddleware, secret=origin_verify_secret(),
                       exempt_paths=(f"{API_PREFIX}/health",))
elif APP_MODE != "local":
    logger.warning("ORIGIN_VERIFY_SECRET no definido: la API acepta peticiones que no pasan por CloudFront")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

# Todas las rutas cuelgan de este router; se monta con API_PREFIX al final del archivo
router = APIRouter()

# ─────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────
class SearchRequest(BaseModel):
    query: str = Field(max_length=500)
    top_n: int = Field(10, ge=1, le=50)

# ─────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────

@router.get("/health")
def health():
    """Verifica que la API esté activa."""
    return {
        "status": "ok",
        "model_loaded": model is not None,
        "articles_loaded": len(df) if df is not None else 0,
    }


@router.post("/search", dependencies=[Depends(rate_limit("search", 60, 60))])
def search(req: SearchRequest):
    """
    Busca artículos similares al texto ingresado.
    Usa BM25 (titulo y tags) combinado con embeddings para ordenar por relevancia.
    """
    if model is None:
        raise HTTPException(status_code=503, detail="Modelo no disponible")
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="La query no puede estar vacía")

    try:
        results = model.search(req.query, top_n=req.top_n)
        return results[DISPLAY_COLUMNS].to_dict(orient="records")
    except Exception as e:
        logger.error(f"Error en /search: {e}")
        raise HTTPException(status_code=500, detail="Error procesando la búsqueda")


@router.get("/recommend/{url:path}", dependencies=[Depends(rate_limit("recommend", 60, 60))])
def recommend(url: str, top_n: int = Query(5, ge=1, le=20)):
    """
    Retorna artículos similares dado el ID de un artículo base.
    """
    if model is None:
        raise HTTPException(status_code=503, detail="Modelo no disponible")

    try:
        base    = df[df["url"] == url].iloc[0][DISPLAY_COLUMNS].to_dict()
        similar = model.recommend_similar(url, top_n=top_n)
        return {
            "base_article":    base,
            "recommendations": similar[DISPLAY_COLUMNS].to_dict(orient="records")
        }
    except Exception as e:
        logger.error(f"Error en /recommend: {e}")
        raise HTTPException(status_code=500, detail="Error generando recomendaciones")


@router.get("/articles", dependencies=[Depends(rate_limit("read", 120, 60))])
def get_articles(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
    """Retorna artículos paginados."""
    if df is None or df.empty:
        raise HTTPException(status_code=503, detail="Datos no disponibles")

    page = df[DISPLAY_COLUMNS].iloc[offset: offset + limit]
    return {
        "total":    len(df),
        "limit":    limit,
        "offset":   offset,
        "articles": page.to_dict(orient="records")
    }


@router.get("/categories", dependencies=[Depends(rate_limit("read", 120, 60))])
def get_categories(limit: int = Query(12, ge=1, le=50)):
    """
    Retorna las categorías de la BD ordenadas por número de artículos (temas más populares primero).
    """
    if df is None or df.empty:
        raise HTTPException(status_code=503, detail="Datos no disponibles")

    counts = df["category_name"].value_counts().head(limit)
    return [
        {"category_name": name, "total": int(total)}
        for name, total in counts.items()
    ]


# Cada resumen es una invocación de SageMaker: límite más estricto
@router.get("/articles/{url:path}/teaser", dependencies=[Depends(rate_limit("teaser", 10, 60))])
def get_article_teaser(url: str):
    """
    Genera el resumen (teaser) del artículo con el modelo Qwen3 desplegado en SageMaker.
    Lo llama el botón 'Ver resumen' de cada card.
    """
    if teaser_model is None:
        raise HTTPException(status_code=503, detail="El resumen con IA no está configurado")
    if df is None or df.empty:
        raise HTTPException(status_code=503, detail="Datos no disponibles")
    if df[df["url"] == url].empty:
        raise HTTPException(status_code=404, detail=f"Artículo '{url}' no encontrado")

    input_text = repo.get_input_text(url)
    if input_text is None:
        raise HTTPException(status_code=404, detail="El artículo no tiene texto para resumir")

    try:
        return {"url": url, "teaser": teaser_model.generate(input_text)}
    except InvalidInputError as e:
        logger.error(f"Texto no válido para el teaser de {url}: {e}")
        raise HTTPException(status_code=422, detail="El texto del artículo no se puede resumir")
    except TeaserGenerationError as e:
        logger.error(f"Error generando el teaser de {url}: {e}")
        raise HTTPException(status_code=502, detail="El modelo no pudo generar el resumen")


@router.get("/articles/{url:path}/related", dependencies=[Depends(rate_limit("recommend", 60, 60))])
def get_related_articles(url: str, top_n: int = Query(5, ge=1, le=20)):
    """
    Dada la url de un artículo seleccionado por el usuario,
    retorna los artículos más similares usando show_recommendations().
    Se expone como botón 'Ver artículos relacionados' en el frontend.
    """
    if model is None:
        raise HTTPException(status_code=503, detail="Modelo no disponible")
    if df is None or df.empty:
        raise HTTPException(status_code=503, detail="Datos no disponibles")

    # Buscar el índice del artículo en el DataFrame
    matches = df[df["url"] == url]
    if matches.empty:
        raise HTTPException(status_code=404, detail=f"Artículo '{url}' no encontrado")


    try:
        similar = model.recommend_similar(url, top_n=top_n)
        base    = df[df["url"] == url].iloc[0][DISPLAY_COLUMNS].to_dict()

        return {
            "base_article":    base,
            "related":         similar[DISPLAY_COLUMNS].to_dict(orient="records")
        }
    except Exception as e:
        logger.error(f"Error en /articles/{url}/related: {e}")
        raise HTTPException(status_code=500, detail="Error generando artículos relacionados")


@router.get("/articles/{url:path}", dependencies=[Depends(rate_limit("read", 120, 60))])
def get_article(url: str):
    """
    Retorna un artículo específico por su url de la BD.
    Se declara al final porque {url:path} tambien capturaria /articles/{url}/related.
    """
    if df is None or df.empty:
        raise HTTPException(status_code=503, detail="Datos no disponibles")

    result = df[df["url"] == url]
    if result.empty:
        raise HTTPException(status_code=404, detail=f"Artículo '{url}' no encontrado")

    return result.iloc[0][DISPLAY_COLUMNS].to_dict()


app.include_router(router, prefix=API_PREFIX)
app.include_router(auth.router, prefix=API_PREFIX)
