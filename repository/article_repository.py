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