interface Props {
  embed_ms: number;
  db_ms: number;
  total_ms: number;
  cache_hit?: boolean;
  cache_layer?: 'none' | 'embed' | 'result';
}

export function LatencyBadge({ embed_ms, db_ms, total_ms, cache_hit, cache_layer }: Props) {
  const layer = cache_layer ?? (cache_hit ? 'embed' : 'none');
  const isResult = layer === 'result';
  const isEmbed = layer === 'embed';

  return (
    <div className="flex items-center gap-3 text-xs font-mono">
      <span
        className={`pill border ${
          isResult
            ? 'bg-lime/25 text-lime border-lime/60'
            : isEmbed
            ? 'bg-lime/15 text-lime border-lime/40'
            : 'bg-ink-800 text-ink-300 border-ink-700'
        }`}
      >
        embed{' '}
        <b className={`ml-1 ${isResult || isEmbed ? 'text-lime' : 'text-accent-glow'}`}>
          {embed_ms}ms
        </b>
        {isResult && <span className="ml-1.5">⚡⚡ result-cache</span>}
        {isEmbed && <span className="ml-1.5">⚡ embed-cache</span>}
      </span>
      <span className="pill bg-ink-800 text-ink-300 border border-ink-700">
        db <b className="text-lime ml-1">{db_ms}ms</b>
      </span>
      <span className="pill bg-accent/15 text-accent-glow border border-accent/40">
        total <b className="ml-1">{total_ms}ms</b>
      </span>
    </div>
  );
}
