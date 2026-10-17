import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sentence_transformers import SentenceTransformer
from rank_bm25 import BM25Okapi


class NLPRecomender:

    def __init__(
            self,
            stop_words="english",
            ngram_range=(1, 2),
            title_weight=0.7,
            tag_weight=0.3,
            k1=1.5,
            b=0.75,
            epsilon=0.25
    ):
        # Se reutiliza el analizador de sklearn (minusculas, token_pattern y
        # stop words) que antes aplicaba TfidfVectorizer, ahora como tokenizador de BM25
        self.title_analyzer = CountVectorizer(
            stop_words=stop_words,
            ngram_range=ngram_range
        ).build_analyzer()

        self.tag_analyzer = CountVectorizer(
            stop_words=stop_words,
            ngram_range=(1, 1)
        ).build_analyzer()

        # Parametros BM25: k1 controla la saturacion de la frecuencia del termino,
        # b la normalizacion por longitud del documento y epsilon el piso del idf
        self.k1 = k1
        self.b = b
        self.epsilon = epsilon

        self.embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
        self.X_emb = None
        self.embedding_weight = 0.5

        self.title_weight = title_weight
        self.tag_weight = tag_weight
        self.id_to_index = {}

        self.title_tokens = None
        self.tag_tokens = None
        self.bm25_title = None
        self.bm25_tag = None
        self.data_df = None


    def fit(self, dataframe: pd.DataFrame, text_columns: list) -> "NLPRecomender":
        """
        Construye los indices BM25 (titulo y tags) y los embeddings usando las columnas indicadas.
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

        # Tokenizar cada campo; la posicion i de cada lista corresponde a la fila i de data_df
        self.title_tokens = [self.title_analyzer(text) for text in self.data_df[title_col].fillna("").astype(str)]
        self.tag_tokens = [self.tag_analyzer(text) for text in self.data_df[tag_col].fillna("").astype(str)]

        # Un indice BM25 por campo, construido una sola vez
        self.bm25_title = self._build_index(self.title_tokens)
        self.bm25_tag = self._build_index(self.tag_tokens)

        combined_text = (
            self.data_df[title_col].fillna("") + " " +
            self.data_df[tag_col].fillna("")
        )

        self.X_emb = self.embedding_model.encode(
            combined_text.tolist(),
            show_progress_bar=True
        )

        self.id_to_index = {
            url: idx
            for idx, url in enumerate(self.data_df["url"])
        }

        return self


    def _build_index(self, corpus_tokens: list):
        """
        Crea un indice BM25Okapi. Devuelve None si ningun documento tiene tokens,
        ya que rank_bm25 no admite un corpus sin vocabulario.
        """
        if not any(corpus_tokens):
            return None
        return BM25Okapi(corpus_tokens, k1=self.k1, b=self.b, epsilon=self.epsilon)


    def _bm25_scores(self, index, query_tokens: list) -> np.ndarray:
        """
        Puntuaciones BM25 de un campo escaladas a [0, 1] dividiendo por el maximo de la consulta.
        El escalado permite combinarlas con los pesos de campo y con la similitud de embeddings.
        """
        scores = np.zeros(len(self.data_df))
        if index is None or not query_tokens:
            return scores

        # BM25Okapi puede dar valores negativos si casi todos los documentos contienen el termino
        scores = np.clip(index.get_scores(query_tokens), 0, None)
        max_score = scores.max()
        if max_score > 0:
            scores = scores / max_score
        return scores


    def _lexical_score(self, title_query: list, tag_query: list) -> np.ndarray:
        """
        Combina las puntuaciones BM25 de titulo y tags con sus pesos.
        """
        return (
            self.title_weight * self._bm25_scores(self.bm25_title, title_query) +
            self.tag_weight * self._bm25_scores(self.bm25_tag, tag_query)
        )


    def search(self, query: str, top_n=5) -> pd.DataFrame:
        """
        Recibe texto libre y devuelve los articulos mas relevantes
        usando BM25 con boost entre titulo y tags
        """

        if self.data_df is None or self.X_emb is None:
            raise ValueError("El modelo no ha sido entrenado. Ejecuta fit() primero.")

        if not query or not query.strip() or top_n <= 0:
            return self.data_df.iloc[[]]

        # Puntuacion BM25 de la consulta en cada campo
        bm25_score = self._lexical_score(
            self.title_analyzer(query),
            self.tag_analyzer(query)
        )

        q_emb = self.embedding_model.encode([query])
        emb_score = cosine_similarity(q_emb, self.X_emb).flatten()

        final_score = (
            0.5 * bm25_score +
            0.5 * emb_score
        )

        # Ordenar resultados descartando los que no tienen puntuacion
        top_indices = self._top_indices(final_score, top_n)

        return self.data_df.iloc[top_indices]


    def recommend_similar(self, url: str, top_n=5) -> pd.DataFrame:
        """
        Recomienda articulos similares usando la url con boost entre titulo y tags.
        Los tokens del articulo se usan como consulta BM25 contra el resto del corpus.
        """

        if self.X_emb is None:
            raise ValueError("El modelo no ha sido entrenado. Ejecuta fit() primero.")

        if url not in self.id_to_index:
            raise ValueError(f"La url '{url}' no existe en el DataFrame.")

        article_index = self.id_to_index[url]

        # Titulo y tags del articulo seleccionado como consulta
        bm25_score = self._lexical_score(
            self.title_tokens[article_index],
            self.tag_tokens[article_index]
        )

        article_emb = self.X_emb[article_index].reshape(1, -1)
        emb_score = cosine_similarity(article_emb, self.X_emb).flatten()

        final_similarity = (
            0.5 * bm25_score +
            0.5 * emb_score
        )

        final_similarity[article_index] = -1

        top_indices = self._top_indices(final_similarity, top_n)

        return self.data_df.iloc[top_indices]


    @staticmethod
    def _top_indices(scores: np.ndarray, top_n: int) -> np.ndarray:
        """
        Indices de mayor a menor puntuacion (orden estable en empates), sin puntuaciones <= 0.
        """
        order = np.argsort(-scores, kind="stable")
        order = order[scores[order] > 0]
        return order[:top_n]
