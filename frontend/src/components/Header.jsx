import { useState, useEffect } from 'react';
import { getHealth } from '../services/api';

export default function Header() {
  const [health, setHealth] = useState(null);

  useEffect(() => {
    getHealth().then(setHealth).catch(() => setHealth({ status: 'down' }));
  }, []);

  const ok = health?.status === 'ok';

  return (
    <header className="app-header">
      {/* NCGR lockup — left */}
      <div className="header-lockup">
        <img className="gov-logo" src="/ncgr-logo.png" alt="NCGR"
          onError={e => { e.target.style.display = 'none'; }} />
        <div className="lockup-names">
          <span className="lockup-name-en">National Center for Government Resources Systems</span>
          <span className="lockup-name-ar" dir="rtl">المركز الوطني لنظم الموارد الحكومية</span>
        </div>
      </div>

      {/* Title + green accent line */}
      <div className="title-block">
        <div className="title-row">
          <h1 className="app-title">NCGR Agentic AI Copilot</h1>
          <div className="accent-line" />
        </div>
      </div>

      {/* Connection status + NCGR logo — right */}
      <div className="flex items-center gap-3">
        <div className="status-pill">
          <span className={`w-2 h-2 rounded-full ${ok ? '' : 'animate-pulse'}`}
            style={{ background: ok ? 'var(--green)' : health ? 'var(--red)' : 'var(--amber)' }} />
          <span>
            {health == null ? 'Connecting…'
              : ok ? 'Connected'
              : health.status === 'unconfigured' ? 'Not configured'
              : 'Backend offline'}
          </span>
        </div>
        {/* NCGR logo — far right */}
        <img className="org-logo" src="/ncgr-logo.png" alt="NCGR"
          onError={e => { e.target.style.display = 'none'; }} />
      </div>
    </header>
  );
}
