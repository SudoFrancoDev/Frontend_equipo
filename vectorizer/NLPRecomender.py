import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import linear_kernel, cosine_similarity


class NLPRecomender:
    
    def __init__(
            self,
            max_df=0.95,
            min_df=5,
            stop_words="english",
            ngram_range=(1, 2)
    ):
        self.vectorizer = TfidfVectorizer(
            max_df=max_df,
            min_df=min_df,
            stop_words=stop_words,
            ngram_range=ngram_range,
            sublinear_tf=True
        )

        self.documents = None
        self.X_tfidf = None
        self.data_df = None
        self.text_columns = None

    
    def fit(self, dataframe: pd.DataFrame, text_columns: list) -> "NLPRecomender":
        """
        Entrena el espacio vectorial usando las columnas indicadas.
        """

        missing = [c for c in text_columns if c not in dataframe.columns]
        if missing:
            raise ValueError(f"Las siguientes columnas no existen en el DataFrame: {missing}")
        if dataframe.empty:
            raise ValueError("El DataFrame está vacío.")

        self.data_df = dataframe.reset_index(drop=True)
        self.text_columns = text_columns

        # Construir corpus combinando columnas
        docs = dataframe[text_columns].agg(" ".join, axis=1)
        self.documents = docs

        # TF-IDF
        self.X_tfidf = self.vectorizer.fit_transform(docs)

        return self
    

    def search(self, query: str, top_n=10) -> pd.DataFrame:
        """
        Recibe texto libre y devuelve los articulos mas similares.
        """

        if self.X_tfidf is None:
            raise ValueError("El modelo no ha sido entrenado. Ejecuta fit() primero.")
        
        # Transformar consulta al espacio TF-IDF
        query_vec = self.vectorizer.transform([query])

        # Calcular similitud 
        scores = linear_kernel(query_vec, self.X_tfidf)

        # Ordenar resultados
        top_indices = scores.argsort()[0][-top_n:][::-1]

        return self.data_df.loc[top_indices]
    

    def recommend_similar(self, article_index, top_n=5) -> pd.DataFrame:
        """
        Recomienda articulos similares dado el indice del articulo base
        """

        if article_index < 0 or article_index >= self.X_tfidf.shape[0]:
            raise IndexError(f"El indice {article_index} del articulo está fuera de rango.")

        # Vector del articulo seleccionado
        article_vector = self.X_tfidf[article_index]

        # Calcular similitud contra todos
        similarities = cosine_similarity(article_vector, self.X_tfidf).flatten()

        # Obtener indices ordenados por similitud descendente
        similar_indices = np.argsort(similarities)[::-1]

        # Excluir el mismo articulo
        similar_indices = similar_indices[similar_indices != article_index]

        # Tomar los top_n
        top_indices = similar_indices[:top_n]

        return self.data_df.iloc[top_indices]
