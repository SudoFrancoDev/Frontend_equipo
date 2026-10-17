import math
import unittest
from collections import Counter
from unittest import mock

import numpy as np
import pandas as pd

from rank_bm25 import BM25Okapi

import vectorizer.NLPRecomender as nlp_module
from vectorizer.NLPRecomender import NLPRecomender


class ZeroEmbedding:
    """Embeddings nulos: la similitud coseno es 0 y solo cuenta BM25."""

    def __init__(self, *args, **kwargs):
        pass

    def encode(self, texts, show_progress_bar=False):
        return np.zeros((len(texts), 4))


class KeywordEmbedding:
    """Embeddings de juguete: textos sobre el espacio en una direccion, el resto en otra."""

    SPACE_WORDS = ("space", "astronomy", "cosmos", "exoplanet", "telescope")

    def __init__(self, *args, **kwargs):
        pass

    def encode(self, texts, show_progress_bar=False):
        return np.array([
            [1.0, 0.0] if set(t.lower().split()) & set(self.SPACE_WORDS) else [0.0, 1.0]
            for t in texts
        ])


ARTICLES = [
    ("Python machine learning tutorial", "programming"),
    ("Deep learning with Python and PyTorch", "artificial intelligence"),
    ("Electric aircraft development gets a boost", "aerospace"),
    ("Space telescope discovers a new exoplanet", "astronomy"),
    ("Learning Python fast: python tips for python beginners", "programming"),
    ("Battery technology for electric cars", "energy"),
    ("Machine learning in medicine", "artificial intelligence"),
    ("Learning to cook pasta", "food"),
    ("Reinforcement learning agents play games", "artificial intelligence"),
    ("Learning languages with apps", "education"),
    ("Online learning platforms grow", "education"),
    (None, None),  # documento sin tokens
]


def make_df():
    df = pd.DataFrame({
        "title": [t for t, _ in ARTICLES],
        "category_name": [g for _, g in ARTICLES],
        "url": [f"https://example.com/article-{i}" for i in range(len(ARTICLES))],
    })
    # Indice no consecutivo para comprobar que no se desalinean filas e indices
    df.index = [100 + 7 * i for i in range(len(df))][::-1]
    return df


def build_model(embedding_cls=ZeroEmbedding, **kwargs):
    with mock.patch.object(nlp_module, "SentenceTransformer", embedding_cls):
        model = NLPRecomender(**kwargs)
    return model.fit(make_df(), ["title", "category_name"])


def manual_bm25(corpus, query, k1=1.5, b=0.75, epsilon=0.25):
    """BM25 Okapi calculado a mano (misma variante de idf con piso epsilon que rank_bm25)."""
    n = len(corpus)
    avgdl = sum(len(d) for d in corpus) / n
    df_counts = Counter(t for d in corpus for t in set(d))
    idf = {t: math.log(n - f + 0.5) - math.log(f + 0.5) for t, f in df_counts.items()}
    floor = epsilon * sum(idf.values()) / len(idf)
    idf = {t: (v if v >= 0 else floor) for t, v in idf.items()}

    scores = []
    for doc in corpus:
        tf = Counter(doc)
        s = 0.0
        for q in query:
            f = tf.get(q, 0)
            s += idf.get(q, 0) * f * (k1 + 1) / (f + k1 * (1 - b + b * len(doc) / avgdl))
        scores.append(s)
    return np.array(scores)


class TestIndexConstruction(unittest.TestCase):

    def test_index_built_with_one_entry_per_article(self):
        model = build_model()
        self.assertEqual(model.bm25_title.corpus_size, len(ARTICLES))
        self.assertEqual(model.bm25_tag.corpus_size, len(ARTICLES))
        self.assertEqual(len(model.title_tokens), len(model.data_df))
        self.assertEqual(model.title_tokens[-1], [])
        self.assertEqual(model.tag_tokens[-1], [])

    def test_tokenization_reuses_existing_normalization(self):
        model = build_model()
        tokens = model.title_tokens[0]
        # minusculas, sin stop words y con bigramas en el titulo
        self.assertIn("python", tokens)
        self.assertIn("machine learning", tokens)
        self.assertEqual(model.tag_analyzer("The Artificial Intelligence"), ["artificial", "intelligence"])

    def test_scores_follow_bm25_formula(self):
        model = build_model()
        query = model.title_analyzer("python learning")
        expected = np.clip(manual_bm25(model.title_tokens, query), 0, None)
        expected = expected / expected.max()
        np.testing.assert_allclose(model._bm25_scores(model.bm25_title, query), expected)

    def test_term_frequency_saturates(self):
        corpus = [["python"], ["python"] * 3, ["python"] * 30] + [[w] for w in "abcdefg"]
        scores = BM25Okapi(corpus, b=0.0).get_scores(["python"])
        np.testing.assert_allclose(scores, manual_bm25(corpus, ["python"], b=0.0))
        self.assertLess(scores[0], scores[1])
        self.assertLess(scores[1], scores[2])
        # con b=0 el limite es idf * (k1 + 1): 30 apariciones casi no suman frente a 3
        self.assertLess(scores[2] / scores[0], 2.5)

    def test_index_not_rebuilt_on_search(self):
        model = build_model()
        title_index = model.bm25_title
        with mock.patch.object(nlp_module, "BM25Okapi") as bm25_cls:
            model.search("python")
            model.recommend_similar("https://example.com/article-0")
            bm25_cls.assert_not_called()
        self.assertIs(model.bm25_title, title_index)

    def test_field_without_tokens_does_not_fail(self):
        df = make_df()
        df["category_name"] = None
        with mock.patch.object(nlp_module, "SentenceTransformer", ZeroEmbedding):
            model = NLPRecomender().fit(df, ["title", "category_name"])
        self.assertIsNone(model.bm25_tag)
        self.assertFalse(model.search("python").empty)


class TestSearch(unittest.TestCase):

    def setUp(self):
        self.model = build_model()

    def lexical(self, query):
        return self.model._lexical_score(
            self.model.title_analyzer(query), self.model.tag_analyzer(query)
        )

    def test_results_sorted_by_bm25_score(self):
        results = self.model.search("python learning")
        positions = [self.model.id_to_index[a] for a in results["url"]]
        scores = self.lexical("python learning")[positions]
        self.assertTrue(np.all(np.diff(scores) <= 0))
        self.assertEqual(positions, list(np.argsort(-self.lexical("python learning"), kind="stable")[:len(positions)]))

    def test_default_returns_at_most_five(self):
        self.assertGreater(int((self.lexical("learning") > 0).sum()), 5)
        self.assertEqual(len(self.model.search("learning")), 5)
        self.assertEqual(len(self.model.search("learning", top_n=3)), 3)

    def test_titles_and_links_match_original_articles(self):
        original = make_df().set_index("url")
        top = self.model.search("exoplanet telescope")
        self.assertEqual(top.iloc[0]["url"], "https://example.com/article-3")
        for _, row in self.model.search("python learning").iterrows():
            self.assertEqual(row["title"], original.loc[row["url"], "title"])
            self.assertEqual(row["category_name"], original.loc[row["url"], "category_name"])

    def test_title_weighs_more_than_tags(self):
        # "programming" solo aparece en tags; "python" en titulos
        self.assertAlmostEqual(self.lexical("programming").max(), self.model.tag_weight)
        self.assertAlmostEqual(self.lexical("python").max(), self.model.title_weight)

    def test_result_columns_unchanged(self):
        results = self.model.search("python")
        self.assertEqual(list(results.columns), ["title", "category_name", "url"])
        self.assertTrue({"title", "url"}.issubset(results.columns))

    def test_empty_and_unmatched_queries(self):
        for query in ["", "   ", "the and of", "zzzzqqq"]:
            results = self.model.search(query)
            self.assertIsInstance(results, pd.DataFrame)
            self.assertTrue(results.empty, query)
        self.assertTrue(self.model.search("python", top_n=0).empty)

    def test_empty_document_never_returned(self):
        results = self.model.search("learning", top_n=50)
        self.assertNotIn("https://example.com/article-11", set(results["url"]))

    def test_untrained_model_raises(self):
        with mock.patch.object(nlp_module, "SentenceTransformer", ZeroEmbedding):
            model = NLPRecomender()
        with self.assertRaises(ValueError):
            model.search("python")

    def test_embeddings_still_contribute(self):
        model = build_model(KeywordEmbedding)
        # "cosmos" no existe en el vocabulario BM25; solo los embeddings lo relacionan
        results = model.search("cosmos", top_n=1)
        self.assertEqual(results.iloc[0]["url"], "https://example.com/article-3")


class TestRecommendSimilar(unittest.TestCase):

    def setUp(self):
        self.model = build_model()

    def test_recommends_lexically_related_articles(self):
        base = "https://example.com/article-0"
        results = self.model.recommend_similar(base)
        self.assertLessEqual(len(results), 5)
        self.assertNotIn(base, set(results["url"]))
        self.assertIn(results.iloc[0]["url"], {
            "https://example.com/article-4", "https://example.com/article-1"
        })

    def test_unknown_article_raises(self):
        with self.assertRaises(ValueError):
            self.model.recommend_similar("https://example.com/missing")

    def test_article_without_tokens_does_not_fail(self):
        results = self.model.recommend_similar("https://example.com/article-11")
        self.assertTrue(results.empty)


if __name__ == "__main__":
    unittest.main()
