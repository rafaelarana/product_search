import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { AppMode, getProduct, getSimilar, ProductDetail, SearchHit } from '../lib/api';
import { ProductCard } from '../components/ProductCard';

interface Props {
  mode: AppMode;
}

export default function ProductPage({ mode }: Props) {
  const { id } = useParams();
  const productId = Number(id);
  const [product, setProduct] = useState<ProductDetail | null>(null);
  const [similar, setSimilar] = useState<SearchHit[]>([]);
  const [similarMs, setSimilarMs] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const backTo = mode === 'turbo' ? '/turbo' : '/';

  useEffect(() => {
    setProduct(null);
    setSimilar([]);
    setSimilarMs(null);
    setError(null);
    if (Number.isNaN(productId)) return;
    getProduct(productId).then(setProduct).catch((e) => setError(e.message));

    const t0 = performance.now();
    getSimilar(productId, 8, mode)
      .then((s) => {
        setSimilar(s);
        setSimilarMs(Math.round(performance.now() - t0));
      })
      .catch(() => {});
  }, [productId, mode]);

  if (error) {
    return (
      <div className="max-w-3xl mx-auto p-10">
        <Link to={backTo} className="text-accent-glow text-sm">
          ← back to search
        </Link>
        <div className="card p-5 mt-5 text-red-300">{error}</div>
      </div>
    );
  }

  if (!product) {
    return <div className="max-w-3xl mx-auto p-10 text-ink-400">Loading…</div>;
  }

  return (
    <div className="max-w-7xl mx-auto px-6 py-10">
      <Link to={backTo} className="text-accent-glow text-sm">
        ← back to search
      </Link>

      <section className="grid grid-cols-1 md:grid-cols-2 gap-8 mt-6">
        <div className="card aspect-square flex items-center justify-center text-9xl font-display text-ink-500">
          {product.product_name.charAt(0).toUpperCase()}
        </div>

        <div>
          {product.product_class && (
            <p className="pill bg-ink-800 text-ink-300 border border-ink-700 mb-3">
              {product.product_class}
            </p>
          )}
          <h1 className="font-display text-3xl font-bold leading-tight text-ink-100">
            {product.product_name}
          </h1>
          {product.average_rating != null && (
            <p className="text-ink-300 mt-2">
              ★ {product.average_rating.toFixed(1)}
              {product.review_count ? ` · ${product.review_count.toLocaleString()} reviews` : ''}
            </p>
          )}
          {product.product_description && (
            <p className="text-ink-200 mt-5 leading-relaxed whitespace-pre-line">
              {product.product_description}
            </p>
          )}
          {product.product_features && (
            <div className="mt-6">
              <h3 className="font-display font-semibold text-ink-100 mb-2">Features</h3>
              <p className="text-ink-300 text-sm whitespace-pre-line">
                {product.product_features}
              </p>
            </div>
          )}
        </div>
      </section>

      <section className="mt-14">
        <div className="flex items-end justify-between mb-1">
          <h2 className="font-display text-2xl font-bold">You might also like</h2>
          {similarMs != null && (
            <span
              className={`pill text-xs font-mono border ${
                mode === 'turbo'
                  ? 'bg-lime/15 text-lime border-lime/40'
                  : 'bg-ink-800 text-ink-300 border-ink-700'
              }`}
            >
              {mode === 'turbo' ? '⚡ precomputed' : 'HNSW'} · <b className="ml-1">{similarMs}ms</b>
            </span>
          )}
        </div>
        <p className="text-ink-400 text-sm mb-6">
          {mode === 'turbo'
            ? 'Top-K neighbors loaded from a materialized view — no HNSW lookup per request.'
            : 'Nearest neighbours in embedding space · pure pgvector cosine'}
        </p>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-5">
          {similar.map((h) => (
            <ProductCard key={h.product_id} hit={h} mode={mode} />
          ))}
        </div>
      </section>
    </div>
  );
}
