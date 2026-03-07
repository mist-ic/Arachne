import { useState, useEffect } from 'react';
import './index.css';
import { LiveFeed } from './pages/LiveFeed';
import { ExtractionStats } from './pages/ExtractionStats';
import { EvasionMap } from './pages/EvasionMap';

type Page = 'feed' | 'extraction' | 'evasion';

const NAV_ITEMS: { id: Page; icon: string; label: string }[] = [
  { id: 'feed', icon: '◉', label: 'Live Feed' },
  { id: 'extraction', icon: '◇', label: 'Extraction Stats' },
  { id: 'evasion', icon: '⬡', label: 'Evasion Map' },
];

function App() {
  const [activePage, setActivePage] = useState<Page>('feed');
  const [clock, setClock] = useState('');

  useEffect(() => {
    const tick = () => {
      const now = new Date();
      setClock(
        now.toLocaleTimeString('en-US', {
          hour12: false,
          hour: '2-digit',
          minute: '2-digit',
          second: '2-digit',
        })
      );
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  const pageTitle = NAV_ITEMS.find((n) => n.id === activePage)?.label ?? '';

  return (
    <div className="app-layout">
      {/* ── Sidebar ─────────────────────────────────────────── */}
      <aside className="sidebar">
        <div className="sidebar-brand">
          <div className="logo-mark">A</div>
          <span className="brand-text">Arachne</span>
          <span className="brand-version">v0.4</span>
        </div>

        <div className="sidebar-section">
          <div className="sidebar-section-label">Operations</div>
          <ul className="sidebar-nav">
            {NAV_ITEMS.map((item) => (
              <li
                key={item.id}
                className={`sidebar-nav-item ${activePage === item.id ? 'active' : ''}`}
                onClick={() => setActivePage(item.id)}
              >
                <span className="nav-icon">{item.icon}</span>
                {item.label}
              </li>
            ))}
          </ul>
        </div>

        <div className="sidebar-section">
          <div className="sidebar-section-label">System</div>
          <ul className="sidebar-nav">
            <li className="sidebar-nav-item">
              <span className="nav-icon">⚙</span>
              Settings
            </li>
            <li className="sidebar-nav-item">
              <span className="nav-icon">◈</span>
              Schema Drift
            </li>
          </ul>
        </div>

        <div className="sidebar-footer">
          <div className="sidebar-status">
            <span className="status-dot" />
            All systems operational
          </div>
        </div>
      </aside>

      {/* ── Header ──────────────────────────────────────────── */}
      <header className="header">
        <div className="flex items-center">
          <span className="header-title">{pageTitle}</span>
          <span className="header-subtitle">// real-time pipeline monitor</span>
        </div>
        <div className="header-actions">
          <span className="header-clock">{clock} UTC</span>
        </div>
      </header>

      {/* ── Main Content ────────────────────────────────────── */}
      <main className="main-content">
        <div className="page-enter" key={activePage}>
          {activePage === 'feed' && <LiveFeed />}
          {activePage === 'extraction' && <ExtractionStats />}
          {activePage === 'evasion' && <EvasionMap />}
        </div>
      </main>
    </div>
  );
}

export default App;
