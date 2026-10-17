-- =====================================================================
--  Load the six CSV files into the tables from create_tables.sql.
--  Run it FROM THE FOLDER THAT CONTAINS THE CSVs (paths are relative):
--     cd output_tables
--     psql -h localhost -U myuser -d news_dw -f /path/to/load_data.sql
--  Everything runs in one transaction: if any row fails, nothing is loaded.
-- =====================================================================
\set ON_ERROR_STOP on
BEGIN;

-- Parents first, then the tables that reference them
\copy dw.dim_date (date_key, full_date, year, quarter, month, month_name, week_of_year, day_of_month, day_of_week, day_name, is_weekend) FROM 'dim_date.csv' WITH (FORMAT csv, HEADER true)
\copy dw.dim_category (category_key, category_code, category_name) FROM 'dim_category.csv' WITH (FORMAT csv, HEADER true)
\copy dw.dim_source (source_key, source_domain, source_name, valid_from, valid_to, is_current) FROM 'dim_source.csv' WITH (FORMAT csv, HEADER true)
\copy dw.dim_article (article_key, url, title) FROM 'dim_article.csv' WITH (FORMAT csv, HEADER true)
\copy dw.fact_article (article_key, date_key, category_key, source_key, published_at, title_length, input_text_words) FROM 'fact_article.csv' WITH (FORMAT csv, HEADER true)
\copy dw.article_content (article_key, input_text) FROM 'article_content.csv' WITH (FORMAT csv, HEADER true)

-- 'infinity' (written by split_articles_csv.py) means "still active" -> store as NULL
UPDATE dw.dim_source SET valid_to = NULL WHERE valid_to = 'infinity';

-- Move the identity counters past the keys that came from the files
DO $$
BEGIN
    PERFORM setval(pg_get_serial_sequence('dw.dim_category', 'category_key'),
                   coalesce((SELECT max(category_key) FROM dw.dim_category), 0) + 1, false);
    PERFORM setval(pg_get_serial_sequence('dw.dim_source', 'source_key'),
                   coalesce((SELECT max(source_key) FROM dw.dim_source), 0) + 1, false);
    PERFORM setval(pg_get_serial_sequence('dw.dim_article', 'article_key'),
                   coalesce((SELECT max(article_key) FROM dw.dim_article), 0) + 1, false);
END $$;

COMMIT;

REFRESH MATERIALIZED VIEW mart.mv_article_cube;
ANALYZE dw.dim_date, dw.dim_category, dw.dim_source,
        dw.dim_article, dw.fact_article, dw.article_content;

-- Quick check: row count per table
SELECT 'dim_date' AS table_name, count(*) AS rows FROM dw.dim_date
UNION ALL SELECT 'dim_category',    count(*) FROM dw.dim_category
UNION ALL SELECT 'dim_source',      count(*) FROM dw.dim_source
UNION ALL SELECT 'dim_article',     count(*) FROM dw.dim_article
UNION ALL SELECT 'fact_article',    count(*) FROM dw.fact_article
UNION ALL SELECT 'article_content', count(*) FROM dw.article_content;
