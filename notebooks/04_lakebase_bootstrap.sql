-- ============================================================================
-- 04 — Lakebase bootstrap
-- ============================================================================
-- Idempotent: applies extensions, the materialized view that types embeddings
-- correctly, indexes, and serving functions. The Synced Table replicates the
-- source Delta into lumen_gold.products_synced with embedding stored as jsonb
-- (Synced Tables don't know about pgvector); we materialize a casted view on
-- top for HNSW indexing.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. Extensions
-- ----------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS databricks_auth;
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

-- ----------------------------------------------------------------------------
-- 2. Materialized view with proper vector type + tsvector for FTS
-- ----------------------------------------------------------------------------
DROP MATERIALIZED VIEW IF EXISTS lumen_gold.products_mv CASCADE;

CREATE MATERIALIZED VIEW lumen_gold.products_mv AS
SELECT
    product_id,
    product_name,
    product_class,
    category_hierarchy,
    product_description,
    product_features,
    average_rating,
    review_count,
    embedding::text::vector(1024) AS embedding,
    to_tsvector(
        'english',
        coalesce(product_name, '')         || ' ' ||
        coalesce(product_description, '')  || ' ' ||
        coalesce(product_class, '')
    ) AS search_vector
FROM lumen_gold.products_synced
WHERE embedding IS NOT NULL;

-- Unique index on PK enables REFRESH MATERIALIZED VIEW CONCURRENTLY
CREATE UNIQUE INDEX idx_products_mv_pk
    ON lumen_gold.products_mv (product_id);

-- HNSW for vector cosine similarity (BGE-large is 1024-dim)
CREATE INDEX idx_products_mv_embedding
    ON lumen_gold.products_mv
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 200);

-- Pre-filter by product_class (the WANDS analog of "distributor")
CREATE INDEX idx_products_mv_class
    ON lumen_gold.products_mv (product_class);

-- Full-text search GIN index
CREATE INDEX idx_products_mv_fts
    ON lumen_gold.products_mv USING gin (search_vector);

-- ----------------------------------------------------------------------------
-- 3. Serving functions
-- ----------------------------------------------------------------------------

-- 3a. Pure semantic search ----------------------------------------------------
CREATE OR REPLACE FUNCTION search_products_semantic(
    query_embedding vector(1024),
    p_class TEXT DEFAULT NULL,
    p_limit INT DEFAULT 20
) RETURNS TABLE (
    product_id INT,
    product_name TEXT,
    product_class TEXT,
    category_hierarchy TEXT,
    average_rating DOUBLE PRECISION,
    review_count INT,
    similarity FLOAT
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        p.product_id,
        p.product_name,
        p.product_class,
        p.category_hierarchy,
        p.average_rating,
        p.review_count,
        (1 - (p.embedding <=> query_embedding))::float AS similarity
    FROM lumen_gold.products_mv p
    WHERE (p_class IS NULL OR p.product_class = p_class)
    ORDER BY p.embedding <=> query_embedding
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql STABLE;

-- 3b. Hybrid search (vector + FTS, RRF combine) -------------------------------
CREATE OR REPLACE FUNCTION search_products_hybrid(
    query_text TEXT,
    query_embedding vector(1024),
    p_class TEXT DEFAULT NULL,
    p_limit INT DEFAULT 20,
    p_vector_weight FLOAT DEFAULT 0.7,
    p_text_weight FLOAT DEFAULT 0.3
) RETURNS TABLE (
    product_id INT,
    product_name TEXT,
    product_class TEXT,
    category_hierarchy TEXT,
    average_rating DOUBLE PRECISION,
    review_count INT,
    combined_score FLOAT
) AS $$
BEGIN
    RETURN QUERY
    WITH vector_results AS (
        SELECT
            p.product_id,
            ROW_NUMBER() OVER (ORDER BY p.embedding <=> query_embedding) AS rk
        FROM lumen_gold.products_mv p
        WHERE (p_class IS NULL OR p.product_class = p_class)
        ORDER BY p.embedding <=> query_embedding
        LIMIT p_limit * 3
    ),
    text_results AS (
        SELECT
            p.product_id,
            ROW_NUMBER() OVER (
                ORDER BY ts_rank(p.search_vector, plainto_tsquery('english', query_text)) DESC
            ) AS rk
        FROM lumen_gold.products_mv p
        WHERE p.search_vector @@ plainto_tsquery('english', query_text)
          AND (p_class IS NULL OR p.product_class = p_class)
        LIMIT p_limit * 3
    ),
    combined AS (
        SELECT
            COALESCE(v.product_id, t.product_id) AS product_id,
            (p_vector_weight * (1.0 / (60 + COALESCE(v.rk, 1000)))) +
            (p_text_weight   * (1.0 / (60 + COALESCE(t.rk, 1000)))) AS rrf_score
        FROM vector_results v
        FULL OUTER JOIN text_results t USING (product_id)
    )
    SELECT
        p.product_id,
        p.product_name,
        p.product_class,
        p.category_hierarchy,
        p.average_rating,
        p.review_count,
        c.rrf_score::float AS combined_score
    FROM combined c
    JOIN lumen_gold.products_mv p USING (product_id)
    ORDER BY c.rrf_score DESC
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql STABLE;

-- 3c. Similar-product recommender --------------------------------------------
CREATE OR REPLACE FUNCTION recommend_similar_products(
    p_product_id INT,
    p_limit INT DEFAULT 10,
    p_same_class BOOLEAN DEFAULT FALSE
) RETURNS TABLE (
    product_id INT,
    product_name TEXT,
    product_class TEXT,
    average_rating DOUBLE PRECISION,
    review_count INT,
    similarity FLOAT
) AS $$
DECLARE
    src_embedding vector(1024);
    src_class TEXT;
BEGIN
    SELECT p.embedding, p.product_class
      INTO src_embedding, src_class
    FROM lumen_gold.products_mv p
    WHERE p.product_id = p_product_id;

    IF src_embedding IS NULL THEN
        RETURN;
    END IF;

    RETURN QUERY
    SELECT
        p.product_id,
        p.product_name,
        p.product_class,
        p.average_rating,
        p.review_count,
        (1 - (p.embedding <=> src_embedding))::float AS similarity
    FROM lumen_gold.products_mv p
    WHERE p.product_id <> p_product_id
      AND (NOT p_same_class OR p.product_class = src_class)
    ORDER BY p.embedding <=> src_embedding
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql STABLE;

-- 3d. Distinct classes (for the UI filter) -----------------------------------
CREATE OR REPLACE FUNCTION list_product_classes(p_limit INT DEFAULT 50)
RETURNS TABLE (product_class TEXT, n BIGINT) AS $$
BEGIN
    RETURN QUERY
    SELECT p.product_class, COUNT(*)::BIGINT AS n
    FROM lumen_gold.products_mv p
    WHERE p.product_class IS NOT NULL AND p.product_class <> ''
    GROUP BY p.product_class
    ORDER BY n DESC
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql STABLE;

-- 3e. Single-product detail lookup -------------------------------------------
CREATE OR REPLACE FUNCTION get_product(p_product_id INT)
RETURNS TABLE (
    product_id INT,
    product_name TEXT,
    product_class TEXT,
    category_hierarchy TEXT,
    product_description TEXT,
    product_features TEXT,
    average_rating DOUBLE PRECISION,
    review_count INT
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        p.product_id, p.product_name, p.product_class, p.category_hierarchy,
        p.product_description, p.product_features,
        p.average_rating, p.review_count
    FROM lumen_gold.products_mv p
    WHERE p.product_id = p_product_id;
END;
$$ LANGUAGE plpgsql STABLE;
