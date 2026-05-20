import { Link } from 'react-router-dom';
import type { AppMode, SearchHit } from '../lib/api';

interface Props {
  hit: SearchHit;
  showScore?: boolean;
  mode?: AppMode;
}

export function ProductCard({ hit, showScore = true, mode = 'standard' }: Props) {
  const score = (hit.score * 100).toFixed(0);
  const to = mode === 'turbo' ? `/turbo/product/${hit.product_id}` : `/product/${hit.product_id}`;
  return (
    <Link
      to={to}
      className="card hover:glow-border transition p-5 flex flex-col gap-3 group"
    >
      <div className="aspect-square bg-gradient-to-br from-ink-700 to-ink-800 rounded-xl flex items-center justify-center text-4xl font-display text-ink-500 group-hover:text-accent-glow transition">
        {hit.product_name.charAt(0).toUpperCase()}
      </div>
      <div className="flex-1">
        <h3 className="font-display font-semibold text-ink-100 leading-tight line-clamp-2">
          {hit.product_name}
        </h3>
        {hit.product_class && (
          <p className="text-xs text-ink-400 mt-1.5">{hit.product_class}</p>
        )}
      </div>
      <div className="flex items-center justify-between text-xs">
        {hit.average_rating != null && (
          <span className="text-ink-300">
            ★ {hit.average_rating.toFixed(1)}
            {hit.review_count ? ` (${hit.review_count})` : ''}
          </span>
        )}
        {showScore && (
          <span className="pill bg-lime/15 text-lime border border-lime/30">
            {score}% match
          </span>
        )}
      </div>
    </Link>
  );
}
