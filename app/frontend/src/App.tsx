import { Link, NavLink, Outlet, useLocation } from 'react-router-dom';

export default function App() {
  const loc = useLocation();
  const onTurbo = loc.pathname.startsWith('/turbo');

  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-ink-700/60 bg-ink-900/80 backdrop-blur sticky top-0 z-20">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <Link to={onTurbo ? '/turbo' : '/'} className="flex items-center gap-2.5 group">
            <span className="w-8 h-8 rounded-lg bg-gradient-to-br from-accent to-lime shadow-glow group-hover:scale-105 transition" />
            <span className="font-display font-bold text-xl tracking-tight">Lumen</span>
            <span className="hidden sm:inline pill bg-ink-800 text-ink-300 border border-ink-700">
              semantic search · powered by Lakebase
            </span>
          </Link>

          {/* Mode tabs */}
          <nav className="flex items-center rounded-full bg-ink-800 p-1 border border-ink-700">
            <NavLink
              to="/"
              end
              className={({ isActive }) =>
                `px-4 py-1.5 text-sm rounded-full transition ${
                  isActive ? 'bg-accent text-ink-900 font-medium' : 'text-ink-300 hover:text-ink-100'
                }`
              }
            >
              Standard
            </NavLink>
            <NavLink
              to="/turbo"
              className={({ isActive }) =>
                `px-4 py-1.5 text-sm rounded-full transition flex items-center gap-1.5 ${
                  isActive ? 'bg-lime text-ink-900 font-medium' : 'text-ink-300 hover:text-ink-100'
                }`
              }
            >
              <span>⚡</span> Turbo
            </NavLink>
          </nav>
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
