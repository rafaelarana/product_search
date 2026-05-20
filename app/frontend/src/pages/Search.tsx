import { FormEvent, useEffect, useState } from 'react';
import {
  search,
  listClasses,
  getCacheStats,
  AppMode,
  CacheStats,
  ClassFacet,
  SearchResponse,
} from '../lib/api';
import { ProductCard } from '../components/ProductCard';
import { LatencyBadge } from '../components/LatencyBadge';

const SAMPLE_QUERIES = [
  'comfy reading chair for small living room',
  'stainless steel kettle',
  'mid-century walnut bookshelf',
  'plush throw pillow for couch',
  'rustic farmhouse dining table',
];

interface Props {
  mode: AppMode;
}

export default function SearchPage({ mode }: Props) {
  const [q, setQ] = useState('');
  const [searchMode, setSearchMode] = useState<'semantic' | 'hybrid'>('semantic');
  const [productClass, setProductClass] = useState<string | null>(null);
  const [result, setResult] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [classes, setClasses] = useState<ClassFacet[]>([]);
  const [cacheStats, setCacheStats] = useState<CacheStats | null>(null);

  useEffect(() => {
    listClasses().then(setClasses).catch(() => {});
  }, []);

  useEffect(() => {
    // Reset state when switching tabs so leftover badges don't confuse.
    setResult(null);
    setError(null);
    if (mode === 'turbo') {
      getCacheStats().then(setCacheStats).catch(() => {});
    } else {
      setCacheStats(null);
    }
  }, [mode]);

  async function run(query: string) {
    setLoading(true);
    setError(null);
    try {
      const res = await search(
        { q: query, mode: searchMode, product_class: productClass },
        mode,
      );
      setResult(res);
      if (mode === 'turbo') {
        getCacheStats().then(setCacheStats).catch(() => {});
      }
    } catch (e: any) {
      setError(e.message ?? String(e));
    } finally {
      setLoading(false);
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (q.trim()) run(q.trim());
  }

  const accent = mode === 'turbo' ? 'lime' : 'accent';

  return (
    <div className="max-w-7xl mx-auto px-6 py-10">
      {/* Hero */}
      <section className="text-center max-w-3xl mx-auto mb-10">
        <h1 className="font-display text-4xl sm:text-5xl font-bold tracking-tight">
          {mode === 'turbo' ? (
            <>
              Find anything, <span className="text-lime">⚡ faster</span>.
            </>
          ) : (
            <>
              Find anything,{' '}
              <span className="bg-gradient-to-r from-accent to-lime bg-clip-text text-transparent">
                semantically
              </span>
              .
            </>
          )}
        </h1>
        <p className="text-ink-300 mt-3">
          {mode === 'turbo'
            ? 'Turbo mode: query embeddings are LRU-cached on the backend; "similar products" reads from a precomputed top-K table. First hit per query is the same; repeats are nearly free.'
            : 'Type how a customer would describe the product. We embed the query with BGE-large and rank 43K items in Lakebase pgvector.'}
        </p>
      </section>

      {/* Search bar */}
      <form
        onSubmit={onSubmit}
        className={`card ${
          mode === 'turbo' ? 'border-lime/40 shadow-[0_0_32px_-4px_rgba(200,255,94,0.35)]' : 'glow-border'
        } p-2 flex items-center gap-2 max-w-3xl mx-auto`}
      >
        <input
          type="text"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="comfy reading chair for small living room…"
          className="flex-1 bg-transparent px-4 py-3 outline-none text-ink-100 placeholder:text-ink-500"
          autoFocus
        />
        <button
          type="submit"
          disabled={loading || !q.trim()}
          className={`px-5 py-2.5 ${
            mode === 'turbo' ? 'bg-lime hover:opacity-90' : 'bg-accent hover:bg-accent-glow'
          } disabled:opacity-50 transition rounded-xl font-medium text-ink-900`}
        >
          {loading ? '…' : mode === 'turbo' ? '⚡ Search' : 'Search'}
        </button>
      </form>

      {/* Sample queries */}
      {!result && (
        <div className="max-w-3xl mx-auto mt-5 flex flex-wrap gap-2 justify-center">
          {SAMPLE_QUERIES.map((s) => (
            <button
              key={s}
              onClick={() => {
                setQ(s);
                run(s);
              }}
              className="pill bg-ink-800 hover:bg-ink-700 text-ink-200 border border-ink-700 transition"
            >
              {s}
            </button>
          ))}
        </div>
      )}

      {/* Controls */}
      <div className="max-w-3xl mx-auto mt-5 flex flex-wrap items-center gap-3 justify-center">
        <div className="inline-flex rounded-full bg-ink-800 p-1 border border-ink-700">
          {(['semantic', 'hybrid'] as const).map((m) => (
            <button
              key={m}
              onClick={() => setSearchMode(m)}
              className={`px-4 py-1.5 text-sm rounded-full transition ${
                searchMode === m
                  ? mode === 'turbo'
                    ? 'bg-lime text-ink-900 font-medium'
                    : 'bg-accent text-ink-900 font-medium'
                  : 'text-ink-300'
              }`}
            >
              {m}
            </button>
          ))}
        </div>

        <select
          value={productClass ?? ''}
          onChange={(e) => setProductClass(e.target.value || null)}
          className={`bg-ink-800 border border-ink-700 text-ink-200 text-sm rounded-full px-4 py-1.5 outline-none focus:border-${accent}`}
        >
          <option value="">All categories</option>
          {classes.map((c) => (
            <option key={c.product_class} value={c.product_class}>
              {c.product_class} ({c.n.toLocaleString()})
            </option>
          ))}
        </select>
      </div>

      {/* Cache stats (Turbo only) */}
      {mode === 'turbo' && cacheStats && (
        <div className="max-w-3xl mx-auto mt-4 text-center text-xs text-ink-400 font-mono space-y-1">
          <div>
            embed cache · size {cacheStats.embed.size}/{cacheStats.embed.maxsize} · hits{' '}
            <span className="text-lime">{cacheStats.embed.hits}</span> · misses{' '}
            <span className="text-ink-200">{cacheStats.embed.misses}</span> · ratio{' '}
            <span className="text-lime">{cacheStats.embed.hit_ratio_pct}%</span>
          </div>
          <div>
            result cache · {cacheStats.result.ready ? 'ready' : 'warming…'} · preloaded{' '}
            <span className="text-lime">{cacheStats.result.preloaded}</span> · hits{' '}
            <span className="text-lime">{cacheStats.result.hits}</span> · misses{' '}
            <span className="text-ink-200">{cacheStats.result.misses}</span> · ratio{' '}
            <span className="text-lime">{cacheStats.result.hit_ratio_pct}%</span>
          </div>
        </div>
      )}

      {/* Results */}
      {error && (
        <div className="mt-10 max-w-3xl mx-auto card p-5 border-red-500/30 text-red-300">
          {error}
        </div>
      )}

      {result && (
        <section className="mt-10">
          <div className="flex items-center justify-between mb-5">
            <p className="text-ink-300 text-sm">
              <b className="text-ink-100">{result.hits.length}</b> results · mode{' '}
              <b className="text-ink-100">{result.mode}</b>
              {mode === 'turbo' && (
                <>
                  {' '}
                  ·{' '}
                  <b className={result.cache_hit ? 'text-lime' : 'text-ink-100'}>
                    {result.cache_hit ? '⚡ cache hit' : 'cache miss'}
                  </b>
                </>
              )}
            </p>
            <LatencyBadge
              embed_ms={result.embed_ms}
              db_ms={result.db_ms}
              total_ms={result.total_ms}
              cache_hit={result.cache_hit}
              cache_layer={result.cache_layer}
            />
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
            {result.hits.map((h) => (
              <ProductCard key={h.product_id} hit={h} mode={mode} />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
