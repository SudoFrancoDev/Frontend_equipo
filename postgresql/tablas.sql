CREATE TABLE dim_date (
    date_key SERIAL PRIMARY KEY,
    full_date TIMESTAMP,
    year INT,
    quarter INT,
    month INT,
    month_name VARCHAR(20),
    day INT,
    day_of_week VARCHAR(20),
    week_of_year INT
);

CREATE TABLE dim_feed_tag (
    feed_tag_key SERIAL PRIMARY KEY,
    feed_tag_name TEXT
);

CREATE TABLE fact_articles (
    article_key SERIAL PRIMARY KEY,
    article_id TEXT UNIQUE,
    title TEXT,
);