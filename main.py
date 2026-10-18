import logging
import os
from contextlib import asynccontextmanager


import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from database.db_connection import PostgreSQLConnection
from repository.article_repository import ArticleRepository
from pipeline.train import train_model, show_recommendations
from vectorizer.NLPRecomender import NLPRecomender
from teaser.teaser_model import TeaserModel, InvalidInputError, TeaserGenerationError

# ─────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DISPLAY_COLUMNS = ["title", "url", "category_name"]

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

    # ── Conectar a PostgreSQL local ────────────
    db = PostgreSQLConnection(
        host="localhost",
        port=5432,
        database="news_dw",
        user="myuser",
        password="admin"
    )
    db.connect()

    # ── Cargar datos y entrenar modelo ─────────
    repo = ArticleRepository(db)
    df = repo.get_articles()
    logger.info(f"Artículos cargados: {len(df)}")

    model = train_model(df)
    logger.info("Modelo NLP entrenado y listo")

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
    title="Medium NLP Recommender API — LOCAL",
    description="API local basada en PostgreSQL + NLPRecomender",
    version="1.0.0-local",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────
class SearchRequest(BaseModel):
    query: str
    top_n: int = 10

# ─────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────

@app.get("/health")
def health():
    """Verifica que la API esté activa."""
    return {
        "status": "ok",
        "model_loaded": model is not None,
        "articles_loaded": len(df) if df is not None else 0,
        "mode": "local-postgresql"
    }


@app.post("/search")
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


@app.get("/recommend/{url:path}")
def recommend(url: str, top_n: int = 5):
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


@app.get("/articles")
def get_articles(limit: int = 50, offset: int = 0):
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


@app.get("/categories")
def get_categories(limit: int = 12):
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


@app.get("/articles/{url:path}/teaser")
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


@app.get("/articles/{url:path}/related")
def get_related_articles(url: str, top_n: int = 5):
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


@app.get("/articles/{url:path}")
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
