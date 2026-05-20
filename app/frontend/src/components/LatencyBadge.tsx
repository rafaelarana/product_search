interface Props {
  embed_ms: number;
  db_ms: number;
  total_ms: number;
  cache_hit?: boolean;
}

export function LatencyBadge({ embed_ms, db_ms, total_ms, cache_hit }: Props) {
  return (
    <div className="flex items-center gap-3 text-xs font-mono">
      <span
        className={`pill border ${
          cache_hit
            ? 'bg-lime/15 text-lime border-lime/40'
            : 'bg-ink-800 text-ink-300 border-ink-700'
        }`}
      >
        embed{' '}
        <b className={`ml-1 ${cache_hit ? 'text-lime' : 'text-accent-glow'}`}>{embed_ms}ms</b>
        {cache_hit ? <span className="ml-1.5">⚡ cached</span> : null}
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
