import logging
import pandas as pd
from vectorizer.NLPRecomender import NLPRecomender

# ─────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────
logger = logging.getLogger(__name__)

DISPLAY_COLUMNS = ["title", "article_id"]


def train_model(df: pd.DataFrame) -> NLPRecomender:
    """
    Entrena el modelo NLP con los artículos cargados desde la BD.
    """
    if df.empty:
        raise ValueError("El DataFrame está vacío. No se puede entrenar el modelo.")

    logger.info(f"Entrenando modelo con {len(df)} artículos...")
    model = NLPRecomender()
    model.fit(df, ["title", "feed_tag_name"])
    logger.info("Modelo entrenado exitosamente.")
    return model


def get_recommendations(model: NLPRecomender, article_id: str, top_n: int = 5) -> pd.DataFrame:
    """
    Retorna los artículos más similares dado un article_id.
    """
    return model.recommend_similar(article_id, top_n=top_n)


def show_recommendations(model: NLPRecomender, article_id: str, top_n: int = 5) -> pd.DataFrame:
    """
    Loguea el artículo base y los artículos recomendados.
    Retorna el DataFrame de artículos similares.
    """
    similar = get_recommendations(model, article_id, top_n)

    base = model.data_df[model.data_df["article_id"] == article_id][DISPLAY_COLUMNS]
    logger.info(f"\nArtículo base:\n{base.to_string(index=False)}")
    logger.info(f"\nArtículos recomendados:\n{similar[DISPLAY_COLUMNS].to_string(index=False)}")

    return similar