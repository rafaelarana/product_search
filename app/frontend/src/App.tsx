import { Link, Outlet } from 'react-router-dom';

export default function App() {
  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-ink-700/60 bg-ink-900/80 backdrop-blur sticky top-0 z-20">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <Link to="/" className="flex items-center gap-2.5 group">
            <span className="w-8 h-8 rounded-lg bg-gradient-to-br from-accent to-lime shadow-glow group-hover:scale-105 transition" />
            <span className="font-display font-bold text-xl tracking-tight">Lumen</span>
            <span className="hidden sm:inline pill bg-ink-800 text-ink-300 border border-ink-700">
              semantic search · powered by Lakebase
            </span>
          </Link>
          <a
            href="https://docs.databricks.com/aws/en/oltp/projects/about"
            target="_blank"
            rel="noreferrer"
            className="text-sm text-ink-300 hover:text-ink-100"
          >
            docs ↗
          </a>
        </div>
      </header>

      <main className="flex-1">
        <Outlet />
      </main>

      <footer className="border-t border-ink-700/60 py-6 text-center text-xs text-ink-400">
        <span>43K products · 1024-dim BGE-large · pgvector HNSW · Lakebase Autoscale</span>
      </footer>
    </div>
  );
}
