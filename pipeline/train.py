from vectorizer.NLPRecomender import NLPRecomender
import pandas as pd

DISPLAY_COLUMNS = ["title", "article_id"]

def train_model(df: pd.DataFrame) -> NLPRecomender:
    model = NLPRecomender()
    model.fit(df, ["title", "feed_tag_name"])
    return model

def get_recommendations(model: NLPRecomender, article_index: int=0, top_n: int=5) -> pd.DataFrame:
    return model.recommend_similar(article_index, top_n=top_n)

def show_recommendations(model, article_index = 0, top_n = 5) -> pd.DataFrame:
    
    similar = get_recommendations(model, article_index, top_n)
    print("\n Articulo base:\n")
    print(model.data_df.iloc[article_index][DISPLAY_COLUMNS])

    print("\n Articulos recomendados:\n")
    print(similar[DISPLAY_COLUMNS])
    return similar