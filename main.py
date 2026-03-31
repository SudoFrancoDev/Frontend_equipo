import logging
from contextlib import asynccontextmanager


import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from database.db_connection import PostgreSQLConnection
from repository.article_repository import ArticleRepository
from pipeline.train import train_model, show_recommendations
from vectorizer.NLPRecomender import NLPRecomender

# ─────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DISPLAY_COLUMNS = ["title", "article_id"]

# ─────────────────────────────────────────────
# Estado global (modelo + datos)
# ─────────────────────────────────────────────
model: NLPRecomender = None
df: pd.DataFrame = None

# ─────────────────────────────────────────────
# Startup / Shutdown
# ─────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    global model, df

    # ── Conectar a PostgreSQL local ────────────
    db = PostgreSQLConnection(
        host="localhost",
        port=5432,
        database="mediumdb",
        user="postgres",
        password="root"
    )
    db.connect()

    # ── Cargar datos y entrenar modelo ─────────
    repo = ArticleRepository(db)
    df = repo.get_articles()
    logger.info(f"Artículos cargados: {len(df)}")

    model = train_model(df)
    logger.info("Modelo NLP entrenado y listo")

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
    Usa TF-IDF para calcular similitud semántica.
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


@app.get("/recommend/{article_id}")
def recommend(article_id: str, top_n: int = 5):
    """
    Retorna artículos similares dado el ID de un artículo base.
    """
    if model is None:
        raise HTTPException(status_code=503, detail="Modelo no disponible")

    try:
        base    = df[df["article_id"] == article_id].iloc[0][DISPLAY_COLUMNS].to_dict()
        similar = model.recommend_similar(article_id, top_n=top_n)
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


@app.get("/articles/{article_id}")
def get_article(article_id: str):
    """
    Retorna un artículo específico por su article_id de la BD.
    """
    if df is None or df.empty:
        raise HTTPException(status_code=503, detail="Datos no disponibles")

    result = df[df["article_id"] == article_id]
    if result.empty:
        raise HTTPException(status_code=404, detail=f"Artículo '{article_id}' no encontrado")

    return result.iloc[0][DISPLAY_COLUMNS].to_dict()


@app.get("/articles/{article_id}/related")
def get_related_articles(article_id: str, top_n: int = 5):
    """
    Dado el article_id de un artículo seleccionado por el usuario,
    retorna los artículos más similares usando show_recommendations().
    Se expone como botón 'Ver artículos relacionados' en el frontend.
    """
    if model is None:
        raise HTTPException(status_code=503, detail="Modelo no disponible")
    if df is None or df.empty:
        raise HTTPException(status_code=503, detail="Datos no disponibles")

    # Buscar el índice del artículo en el DataFrame
    matches = df[df["article_id"] == article_id]
    if matches.empty:
        raise HTTPException(status_code=404, detail=f"Artículo '{article_id}' no encontrado")


    try:
        similar = model.recommend_similar(article_id, top_n=top_n)
        base    = df[df["article_id"] == article_id].iloc[0][DISPLAY_COLUMNS].to_dict()

        return {
            "base_article":    base,
            "related":         similar[DISPLAY_COLUMNS].to_dict(orient="records")
        }
    except Exception as e:
        logger.error(f"Error en /articles/{article_id}/related: {e}")
        raise HTTPException(status_code=500, detail="Error generando artículos relacionados")