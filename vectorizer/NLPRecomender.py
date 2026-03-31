import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import linear_kernel, cosine_similarity
from sentence_transformers import SentenceTransformer


class NLPRecomender:
    
    def __init__(
            self,
            max_df=0.95,
            min_df=5,
            stop_words="english",
            ngram_range=(1, 2),
            title_weight=0.7,
            tag_weight=0.3
    ):
        self.title_vectorizer = TfidfVectorizer(
            max_df=max_df,
            min_df=min_df,
            stop_words=stop_words,
            ngram_range=ngram_range,
            sublinear_tf=True
        )

        self.tag_vectorizer = TfidfVectorizer(
            max_df=max_df,
            min_df=min_df,
            stop_words=stop_words,
            ngram_range=(1, 1),
            sublinear_tf=True
        )

        self.embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
        self.X_emb = None
        self.embedding_weight = 0.5

        self.title_weight = title_weight
        self.tag_weight = tag_weight
        self.id_to_index = {}

        self.X_title = None
        self.X_tag = None
        self.data_df = None

    
    def fit(self, dataframe: pd.DataFrame, text_columns: list) -> "NLPRecomender":
        """
        Entrena el espacio vectorial usando las columnas indicadas.
        """

        missing = [c for c in text_columns if c not in dataframe.columns]
        if missing:
            raise ValueError(f"Las siguientes columnas no existen en el DataFrame: {missing}")
        if dataframe.empty:
            raise ValueError("El DataFrame está vacío.")
        
        if len(text_columns) != 2:
            raise ValueError("Se requieren exactamente 2 columnas de texto para título y etiquetas.")

        self.data_df = dataframe.reset_index(drop=True)
        title_col, tag_col = text_columns

        # Construir corpus combinando columnas
        self.X_title = self.title_vectorizer.fit_transform(self.data_df[title_col].fillna(""))
        self.X_tag = self.tag_vectorizer.fit_transform(self.data_df[tag_col].fillna(""))

        combined_text = (
            self.data_df[title_col].fillna("") + " " +
            self.data_df[tag_col].fillna("")
        )

        self.X_emb = self.embedding_model.encode(
            combined_text.tolist(), 
            show_progress_bar=True
        )

        self.id_to_index = {
            article_id: idx 
            for idx, article_id in enumerate(self.data_df["article_id"])
        }

        return self
    

    def search(self, query: str, top_n=10) -> pd.DataFrame:
        """
        Recibe texto libre y devuelve los articulos mas similares
        usando boost entre titulo y tags
        """

        if self.X_title is None or self.X_tag is None or self.X_emb is None:
            raise ValueError("El modelo no ha sido entrenado. Ejecuta fit() primero.")
        
        # Transformar consulta al espacio TF-IDF
        q_title = self.title_vectorizer.transform([query])
        q_tag = self.tag_vectorizer.transform([query])

        # Calcular similitud 
        score_title = linear_kernel(q_title, self.X_title)
        score_tag = linear_kernel(q_tag, self.X_tag)

        # Combinar scores con pesos
        tfidf_score = (
            self.title_weight * score_title + 
            self.tag_weight * score_tag
            ).flatten()
        
        q_emb = self.embedding_model.encode([query])
        emb_score = cosine_similarity(q_emb, self.X_emb).flatten()

        final_score = (
            0.5 * tfidf_score +
            0.5 * emb_score
        )

        # Ordenar resultados
        top_indices = np.argsort(final_score)[-top_n:][::-1]

        return self.data_df.loc[top_indices]
    

    def recommend_similar(self, article_id: str, top_n=5) -> pd.DataFrame:
        """
        Recomienda articulos similares usando el article_id (link) con boost entre titulo y tags
        """

        if self.X_emb is None:
            raise ValueError("El modelo no ha sido entrenado. Ejecuta fit() primero.")
        
        if article_id not in self.id_to_index:
            raise ValueError(f"El article_id '{article_id}' no existe en el DataFrame.")
        
        article_index = self.id_to_index[article_id]

        # Vector del articulo seleccionado
        article_title_vec = self.X_title[article_index]
        article_tag_vec = self.X_tag[article_index]

        # Calcular similitud contra todos
        sim_title = cosine_similarity(article_title_vec, self.X_title).flatten()
        sim_tag = cosine_similarity(article_tag_vec, self.X_tag).flatten()

        # Obtener indices ordenados por similitud descendente
        tfidf_score = (
            self.title_weight * sim_title + 
            self.tag_weight * sim_tag
        )

        article_emb = self.X_emb[article_index].reshape(1, -1)
        emb_score = cosine_similarity(article_emb, self.X_emb).flatten()

        final_similarity = (
            0.5 * tfidf_score +
            0.5 * emb_score
        )

        final_similarity[article_index] = -1  

        top_indices = np.argsort(final_similarity)[-top_n:][::-1]

        return self.data_df.iloc[top_indices]