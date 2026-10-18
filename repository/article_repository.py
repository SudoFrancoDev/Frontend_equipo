import pandas as pd

class ArticleRepository:
    def __init__(self, db_connection):
        self.db = db_connection

    def get_articles(self) -> pd.DataFrame:
        """
        Recupera los artículos de la base de datos y los devuelve como un DataFrame.
        """
        query = """
            SELECT
            da.title,
            da.url,
            dc.category_name
            FROM dw.fact_article fa
            JOIN dw.dim_article da
                ON da.article_key = fa.article_key
            JOIN dw.dim_category dc
                ON dc.category_key = fa.category_key
            ORDER BY fa.article_key;"""
        
        return self.db.query_to_dataframe(query)

    def get_input_text(self, url: str):
        """
        Devuelve el input_text (texto depurado del artículo) para generar el teaser,
        o None si el artículo no existe o no tiene texto.
        """
        query = """
            SELECT ac.input_text
            FROM dw.dim_article da
            JOIN dw.article_content ac
                ON ac.article_key = da.article_key
            WHERE da.url = %s;"""

        result = self.db.query_to_dataframe(query, params=(url,))
        if result.empty or pd.isna(result.iloc[0]["input_text"]):
            return None
        return result.iloc[0]["input_text"]