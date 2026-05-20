import { FormEvent, useEffect, useRef, useState } from 'react';
import {
  BenchmarkConfig,
  BenchmarkStatus,
  BucketStats,
  getBenchmarkStatus,
  getCurrentBenchmark,
  startBenchmark,
  stopBenchmark,
} from '../lib/api';

const DEFAULT_CFG: BenchmarkConfig = {
  workers: 10,
  duration_s: 30,
  turbo_pct: 50,
  hybrid_pct: 30,
  limit: 20,
};

export default function BenchmarkPage() {
  const [cfg, setCfg] = useState<BenchmarkConfig>(DEFAULT_CFG);
  const [status, setStatus] = useState<BenchmarkStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<number | null>(null);

  // Stop polling when component unmounts; pick up any in-flight job on mount.
  useEffect(() => {
    (async () => {
      try {
        const { job_id } = await getCurrentBenchmark();
        if (job_id) {
          const s = await getBenchmarkStatus(job_id);
          setStatus(s);
          if (s.state === 'running') startPolling(job_id);
        }
      } catch {
        /* no-op */
      }
    })();
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function startPolling(jobId: string) {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = window.setInterval(async () => {
      try {
        const s = await getBenchmarkStatus(jobId);
        setStatus(s);
        if (s.state !== 'running') {
          if (pollRef.current) clearInterval(pollRef.current);
          pollRef.current = null;
        }
      } catch (e: any) {
        setError(e.message ?? String(e));
      }
    }, 500);
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setStatus(null);
    try {
      const { job_id } = await startBenchmark(cfg);
      startPolling(job_id);
    } catch (e: any) {
      setError(e.message ?? String(e));
    }
  }

  async function onStop() {
    if (!status?.job_id) return;
    try {
      const s = await stopBenchmark(status.job_id);
      setStatus(s);
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = null;
    } catch (e: any) {
      setError(e.message ?? String(e));
    }
  }

  const running = status?.state === 'running';

  return (
    <div className="max-w-7xl mx-auto px-6 py-10">
      {/* Hero */}
      <section className="text-center max-w-3xl mx-auto mb-10">
        <h1 className="font-display text-4xl sm:text-5xl font-bold tracking-tight">
          🧪 In-app Benchmark
        </h1>
        <p className="text-ink-300 mt-3">
          Fire concurrent search requests from the App at itself (over the
          local socket, no Apps edge auth in the way), comparing Standard and
          Turbo head-to-head. Results show throughput and full latency
          percentiles per request bucket.
        </p>
      </section>

      {/* Config form */}
      <form
        onSubmit={onSubmit}
        className="card max-w-3xl mx-auto p-6 grid grid-cols-2 sm:grid-cols-3 gap-5"
      >
        <NumberField
          label="Workers"
          value={cfg.workers}
          onChange={(v) => setCfg({ ...cfg, workers: v })}
          min={1}
          max={100}
          hint="1–100 concurrent"
        />
        <NumberField
          label="Duration (s)"
          value={cfg.duration_s}
          onChange={(v) => setCfg({ ...cfg, duration_s: v })}
          min={5}
          max={300}
          hint="5–300 s"
        />
        <NumberField
          label="Limit per query"
          value={cfg.limit}
          onChange={(v) => setCfg({ ...cfg, limit: v })}
          min={1}
          max={50}
          hint="hits per response"
        />
        <NumberField
          label="Turbo %"
          value={cfg.turbo_pct}
          onChange={(v) => setCfg({ ...cfg, turbo_pct: v })}
          min={0}
          max={100}
          hint="0=all Standard, 100=all Turbo"
        />
        <NumberField
          label="Hybrid %"
          value={cfg.hybrid_pct}
          onChange={(v) => setCfg({ ...cfg, hybrid_pct: v })}
          min={0}
          max={100}
          hint="rest is semantic"
        />
        <div className="flex items-end gap-2 col-span-2 sm:col-span-1">
          <button
            type="submit"
            disabled={running}
            className="flex-1 px-5 py-2.5 bg-lime hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed transition rounded-xl font-medium text-ink-900"
          >
            {running ? `Running ${status?.elapsed_s?.toFixed?.(1) ?? 0}s…` : '▶ Run benchmark'}
          </button>
          {running && (
            <button
              type="button"
              onClick={onStop}
              className="px-4 py-2.5 bg-red-500/20 hover:bg-red-500/30 border border-red-500/50 text-red-200 transition rounded-xl font-medium"
              title="Stop the running benchmark"
            >
              ■ Stop
            </button>
          )}
        </div>
      </form>

      {/* Progress / status */}
      {running && status && (
        <div className="max-w-3xl mx-auto mt-5">
          <div className="h-2 rounded-full bg-ink-800 overflow-hidden border border-ink-700">
            <div
              className="h-full bg-lime transition-all"
              style={{ width: `${status.progress_pct}%` }}
            />
          </div>
          <p className="text-center text-xs text-ink-400 font-mono mt-2">
            job {status.job_id} · elapsed {status.elapsed_s.toFixed(1)}s /{' '}
            {status.config.duration_s}s · {status.progress_pct}%
          </p>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="mt-6 max-w-3xl mx-auto card p-5 border-red-500/30 text-red-300">
          {error}
        </div>
      )}

      {/* Results */}
      {(status?.state === 'done' || status?.state === 'stopped') && status.result && (
        <ResultsCard status={status} stopped={status.state === 'stopped'} />
      )}

      {status?.state === 'stopped' && !status.result && (
        <div className="mt-6 max-w-3xl mx-auto card p-5 border-yellow-500/30 text-yellow-200">
          Benchmark stopped before collecting samples.
        </div>
      )}

      {status?.state === 'failed' && (
        <div className="mt-6 max-w-3xl mx-auto card p-5 border-red-500/30 text-red-300">
          Benchmark failed: {status.error ?? 'unknown error'}
        </div>
      )}
    </div>
  );
}

interface NumberFieldProps {
  label: string;
  value: number;
  onChange: (v: number) => void;
  min: number;
  max: number;
  hint?: string;
}

function NumberField({ label, value, onChange, min, max, hint }: NumberFieldProps) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-xs uppercase tracking-wider text-ink-400">{label}</span>
      <input
        type="number"
        min={min}
        max={max}
        value={value}
        onChange={(e) => onChange(Math.max(min, Math.min(max, Number(e.target.value) || min)))}
        className="bg-ink-900 border border-ink-700 rounded-lg px-3 py-2 text-ink-100 font-mono outline-none focus:border-lime"
      />
      {hint && <span className="text-xs text-ink-500">{hint}</span>}
    </label>
  );
}

function ResultsCard({ status, stopped }: { status: BenchmarkStatus; stopped?: boolean }) {
  const r = status.result!;

  // Sort buckets: standard:* first, then turbo:* (just for visual stability).
  const sortedBuckets = [...r.buckets].sort((a, b) => a.name.localeCompare(b.name));

  return (
    <section className="mt-8 max-w-5xl mx-auto">
      <header className="flex items-end justify-between mb-3">
        <div>
          <h2 className="font-display text-2xl font-bold flex items-center gap-2">
            Results
            {stopped && (
              <span className="pill text-xs bg-yellow-500/15 text-yellow-200 border border-yellow-500/40">
                stopped early
              </span>
            )}
          </h2>
          <p className="text-sm text-ink-400 mt-0.5">
            {r.total_requests.toLocaleString()} requests · {r.aggregate_rps} req/s ·{' '}
            {r.total_errors} errors · {r.elapsed_s.toFixed(1)}s elapsed
          </p>
        </div>
        <div className="flex gap-2 text-xs">
          {Object.entries(r.status_codes).map(([code, n]) => (
            <span
              key={code}
              className={`pill border ${
                code === '200'
                  ? 'bg-lime/15 text-lime border-lime/40'
                  : 'bg-red-500/15 text-red-300 border-red-500/40'
              }`}
            >
              {code} × {n.toLocaleString()}
            </span>
          ))}
        </div>
      </header>

      {/* Per-bucket table */}
      <div className="card overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-ink-800/60 border-b border-ink-700">
            <tr className="text-left text-ink-400">
              <th className="px-4 py-2.5 font-medium">Bucket</th>
              <th className="px-3 py-2.5 font-medium text-right">reqs</th>
              <th className="px-3 py-2.5 font-medium text-right">req/s</th>
              <th className="px-3 py-2.5 font-medium text-right">avg</th>
              <th className="px-3 py-2.5 font-medium text-right">p50</th>
              <th className="px-3 py-2.5 font-medium text-right">p75</th>
              <th className="px-3 py-2.5 font-medium text-right">p95</th>
              <th className="px-3 py-2.5 font-medium text-right">p99</th>
              <th className="px-3 py-2.5 font-medium text-right">max</th>
              <th className="px-3 py-2.5 font-medium text-right">errs</th>
            </tr>
          </thead>
          <tbody className="font-mono">
            {sortedBuckets.map((b) => (
              <BucketRow key={b.name} b={b} />
            ))}
            <tr className="bg-accent/10 border-t-2 border-accent/40">
              <td className="px-4 py-2.5 font-display font-semibold">Aggregate</td>
              <td className="px-3 py-2.5 text-right">{r.aggregate.requests.toLocaleString()}</td>
              <td className="px-3 py-2.5 text-right">{r.aggregate.req_per_s}</td>
              <td className="px-3 py-2.5 text-right">{r.aggregate.avg_ms}</td>
              <td className="px-3 py-2.5 text-right">{r.aggregate.p50_ms}</td>
              <td className="px-3 py-2.5 text-right">{r.aggregate.p75_ms}</td>
              <td className="px-3 py-2.5 text-right">{r.aggregate.p95_ms}</td>
              <td className="px-3 py-2.5 text-right">{r.aggregate.p99_ms}</td>
              <td className="px-3 py-2.5 text-right">{r.aggregate.max_ms}</td>
              <td className="px-3 py-2.5 text-right">{r.aggregate.errors}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <p className="text-xs text-ink-500 mt-3">
        Times are in ms. Workers fire requests against{' '}
        <code className="text-ink-300">http://127.0.0.1:8000</code> from inside the App, so the
        numbers reflect backend latency only (no Apps edge auth, no laptop ⇄ Azure RTT). Note: the
        first ~3-5 s of Turbo data is the cache warming up; after that the cache hit rate
        approaches 100%.
      </p>
    </section>
  );
}

function BucketRow({ b }: { b: BucketStats }) {
  const isTurbo = b.name.startsWith('turbo');
  const tone = isTurbo ? 'text-lime' : 'text-ink-300';
  return (
    <tr className="border-b border-ink-700/60 last:border-0">
      <td className={`px-4 py-2.5 font-display ${isTurbo ? 'text-lime' : ''}`}>{b.name}</td>
      <td className="px-3 py-2.5 text-right">{b.requests.toLocaleString()}</td>
      <td className={`px-3 py-2.5 text-right ${tone}`}>{b.req_per_s}</td>
      <td className="px-3 py-2.5 text-right">{b.avg_ms}</td>
      <td className="px-3 py-2.5 text-right">{b.p50_ms}</td>
      <td className="px-3 py-2.5 text-right">{b.p75_ms}</td>
      <td className="px-3 py-2.5 text-right">{b.p95_ms}</td>
      <td className={`px-3 py-2.5 text-right ${tone}`}>{b.p99_ms}</td>
      <td className="px-3 py-2.5 text-right">{b.max_ms}</td>
      <td className={`px-3 py-2.5 text-right ${b.errors > 0 ? 'text-red-300' : 'text-ink-500'}`}>
        {b.errors}
      </td>
    </tr>
  );
}
