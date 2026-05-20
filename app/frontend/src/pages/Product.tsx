import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { getProduct, getSimilar, ProductDetail, SearchHit } from '../lib/api';
import { ProductCard } from '../components/ProductCard';

export default function ProductPage() {
  const { id } = useParams();
  const productId = Number(id);
  const [product, setProduct] = useState<ProductDetail | null>(null);
  const [similar, setSimilar] = useState<SearchHit[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setProduct(null);
    setSimilar([]);
    setError(null);
    if (Number.isNaN(productId)) return;
    getProduct(productId).then(setProduct).catch((e) => setError(e.message));
    getSimilar(productId, 8).then(setSimilar).catch(() => {});
  }, [productId]);

  if (error) {
    return (
      <div className="max-w-3xl mx-auto p-10">
        <Link to="/" className="text-accent-glow text-sm">
          ← back to search
        </Link>
        <div className="card p-5 mt-5 text-red-300">{error}</div>
      </div>
    );
  }

  if (!product) {
    return (
      <div className="max-w-3xl mx-auto p-10 text-ink-400">Loading…</div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto px-6 py-10">
      <Link to="/" className="text-accent-glow text-sm">
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
        <h2 className="font-display text-2xl font-bold mb-1">You might also like</h2>
        <p className="text-ink-400 text-sm mb-6">
          Nearest neighbours in embedding space · pure pgvector cosine
        </p>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-5">
          {similar.map((h) => (
            <ProductCard key={h.product_id} hit={h} />
          ))}
        </div>
      </section>
    </div>
  );
}
