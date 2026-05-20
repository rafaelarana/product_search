import { FormEvent, useEffect, useState } from 'react';
import { search, listClasses, SearchResponse, ClassFacet } from '../lib/api';
import { ProductCard } from '../components/ProductCard';
import { LatencyBadge } from '../components/LatencyBadge';

const SAMPLE_QUERIES = [
  'comfy reading chair for small living room',
  'stainless steel kettle',
  'mid-century walnut bookshelf',
  'plush throw pillow for couch',
  'rustic farmhouse dining table',
];

export default function SearchPage() {
  const [q, setQ] = useState('');
  const [mode, setMode] = useState<'semantic' | 'hybrid'>('semantic');
  const [productClass, setProductClass] = useState<string | null>(null);
  const [result, setResult] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [classes, setClasses] = useState<ClassFacet[]>([]);

  useEffect(() => {
    listClasses().then(setClasses).catch(() => {});
  }, []);

  async function run(query: string) {
    setLoading(true);
    setError(null);
    try {
      const res = await search({ q: query, mode, product_class: productClass });
      setResult(res);
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

  return (
    <div className="max-w-7xl mx-auto px-6 py-10">
      {/* Hero */}
      <section className="text-center max-w-3xl mx-auto mb-10">
        <h1 className="font-display text-4xl sm:text-5xl font-bold tracking-tight">
          Find anything, <span className="bg-gradient-to-r from-accent to-lime bg-clip-text text-transparent">semantically</span>.
        </h1>
        <p className="text-ink-300 mt-3">
          Type how a customer would describe the product. We embed the query with BGE-large
          and rank 43K items in Lakebase pgvector.
        </p>
      </section>

      {/* Search bar */}
      <form onSubmit={onSubmit} className="card glow-border p-2 flex items-center gap-2 max-w-3xl mx-auto">
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
          className="px-5 py-2.5 bg-accent hover:bg-accent-glow disabled:opacity-50 transition rounded-xl font-medium text-ink-900"
        >
          {loading ? '…' : 'Search'}
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
              onClick={() => setMode(m)}
              className={`px-4 py-1.5 text-sm rounded-full transition ${
                mode === m ? 'bg-accent text-ink-900 font-medium' : 'text-ink-300'
              }`}
            >
              {m}
            </button>
          ))}
        </div>

        <select
          value={productClass ?? ''}
          onChange={(e) => setProductClass(e.target.value || null)}
          className="bg-ink-800 border border-ink-700 text-ink-200 text-sm rounded-full px-4 py-1.5 outline-none focus:border-accent"
        >
          <option value="">All categories</option>
          {classes.map((c) => (
            <option key={c.product_class} value={c.product_class}>
              {c.product_class} ({c.n.toLocaleString()})
            </option>
          ))}
        </select>
      </div>

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
            </p>
            <LatencyBadge
              embed_ms={result.embed_ms}
              db_ms={result.db_ms}
              total_ms={result.total_ms}
            />
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
            {result.hits.map((h) => (
              <ProductCard key={h.product_id} hit={h} />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
