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
            fa.title, 
            fa.article_id, 
            dft.feed_tag_name 
            FROM fact_articles fa  
            JOIN dim_feed_tag dft 
                ON fa.article_key = dft.feed_tag_key;"""
        
        return self.db.query_to_dataframe(query)