interface Props {
  embed_ms: number;
  db_ms: number;
  total_ms: number;
}

export function LatencyBadge({ embed_ms, db_ms, total_ms }: Props) {
  return (
    <div className="flex items-center gap-3 text-xs font-mono">
      <span className="pill bg-ink-800 text-ink-300 border border-ink-700">
        embed <b className="text-accent-glow ml-1">{embed_ms}ms</b>
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
