import React, { useState, useEffect } from 'react';
import { Link, Routes, Route, useLocation } from 'react-router-dom';
import { LayoutDashboard, History, Settings, Bot, ArrowLeft, RefreshCw, LogOut, LogIn } from 'lucide-react';

const API_URL = (import.meta.env.VITE_API_URL || '/api').replace(/\/$/, '');
const ApiContext = React.createContext(null);

function Sidebar({ onLogout }) {
  const location = useLocation();

  const navItems = [
    { path: '/app', icon: LayoutDashboard, label: 'Open Trades' },
    { path: '/app/history', icon: History, label: 'History' },
    { path: '/app/settings', icon: Settings, label: 'Settings' },
  ];

  return (
    <div className="sidebar">
      <div style={{ padding: '16px', marginBottom: '24px', display: 'flex', alignItems: 'center', gap: '12px' }}>
        <Bot size={28} color="var(--primary)" />
        <h3 style={{ margin: 0, fontSize: '1.2rem' }}>Bot<span className="text-gradient">23</span></h3>
      </div>

      {navItems.map(item => (
        <Link
          key={item.path}
          to={item.path}
          className={`nav-item ${location.pathname === item.path ? 'active' : ''}`}
        >
          <item.icon size={20} />
          <span>{item.label}</span>
        </Link>
      ))}

      <div style={{ flex: 1 }}></div>

      <button className="nav-item sign-out" onClick={onLogout}>
        <LogOut size={20} /><span>Sign Out</span>
      </button>
      <Link to="/about" className="nav-item" style={{ marginTop: 'auto' }}>
        <ArrowLeft size={20} />
        <span>Back to Site</span>
      </Link>
    </div>
  );
}

function OpenTrades() {
  const request = React.useContext(ApiContext);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const fetchStatus = React.useCallback(() => {
    setLoading(true);
    setError('');
    request('/status')
      .then(json => {
        setData(json);
        setLoading(false);
      })
      .catch(err => {
        setError(err.message);
        setLoading(false);
      });
  }, [request]);

  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  if (loading && !data) return <div className="animate-fade-in">Loading dashboard...</div>;
  if (!data) return <p role="alert" className="api-error">{error}</p>;

  return (
    <div className="animate-fade-in">
      <div className="view-heading">
        <h2>Futures Paper</h2>
        <button className="btn-secondary icon-button" title="Refresh portfolio" aria-label="Refresh portfolio" onClick={fetchStatus} disabled={loading}>
          <RefreshCw size={18} className={loading ? 'spin' : ''} />
        </button>
      </div>
      {error && <p role="alert" className="api-error">{error}</p>}

      <div className="stats-grid">
        <div className="glass-panel stat-card">
          <div className="stat-label">Marked Equity</div>
          <div className="stat-value">${data.portfolio_value?.toFixed(2) || '0.00'}</div>
        </div>
        <div className="glass-panel stat-card">
          <div className="stat-label">Free Cash</div>
          <div className="stat-value">${data.cash_balance?.toFixed(2) || '0.00'}</div>
        </div>
        <div className="glass-panel stat-card">
          <div className="stat-label">Open Positions</div>
          <div className="stat-value">{data.open_positions?.length || 0}</div>
        </div>
      </div>

      <div className="stats-grid">
        <div className="glass-panel stat-card"><div className="stat-label">Realized Net P&L</div><div className="stat-value">${data.stats?.total_net_pnl_usd?.toFixed(2) || '0.00'}</div></div>
        <div className="glass-panel stat-card"><div className="stat-label">Net Equity Estimate</div><div className="stat-value">${data.estimated_net_equity?.toFixed(2) || '0.00'}</div></div>
        <div className="glass-panel stat-card"><div className="stat-label">Expectancy / Trade</div><div className="stat-value">${data.stats?.expectancy_usd?.toFixed(2) || '0.00'}</div></div>
      </div>
      <div className="table-section">
        <h3 style={{ marginBottom: '24px' }}>Open Positions</h3>
        {data.open_positions?.length > 0 ? (
          <div style={{ overflowX: 'auto' }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Lev</th>
                  <th>Margin</th>
                  <th>Entry</th>
                  <th>Current</th>
                  <th>P&L %</th>
                  <th>P&L $</th>
                </tr>
              </thead>
              <tbody>
                {data.open_positions.map((pos, i) => (
                  <tr key={i}>
                    <td style={{ fontWeight: 600 }}>{pos.symbol}</td>
                    <td>{pos.leverage}x</td>
                    <td>${pos.margin_used?.toFixed(2)}</td>
                    <td>${pos.entry_price?.toFixed(4)}</td>
                    <td>${pos.last_known_price?.toFixed(4) || pos.entry_price?.toFixed(4)}</td>
                    <td className={pos.pnl_pct >= 0 ? 'stat-value positive' : 'stat-value negative'} style={{ fontSize: '1rem' }}>
                      {pos.pnl_pct > 0 ? '+' : ''}{pos.pnl_pct.toFixed(2)}%
                    </td>
                    <td className={pos.pnl_usd >= 0 ? 'stat-value positive' : 'stat-value negative'} style={{ fontSize: '1rem' }}>
                      {pos.pnl_usd > 0 ? '+' : ''}${pos.pnl_usd?.toFixed(2)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p style={{ color: 'var(--text-muted)' }}>No open positions currently.</p>
        )}
      </div>
    </div>
  );
}

function HistoryLog() {
  const request = React.useContext(ApiContext);
  const [data, setData] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    request('/history')
      .then(json => setData(json))
      .catch(err => setError(err.message));
  }, [request]);

  if (error) return <p role="alert" className="api-error">{error}</p>;
  if (!data) return <div className="animate-fade-in">Loading history...</div>;

  return (
    <div className="animate-fade-in">
      <h2 style={{ marginBottom: '32px' }}>Trade History</h2>
      <div className="table-section">
        <div style={{ overflowX: 'auto' }}>
          <table className="data-table">
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Entry</th>
                <th>Exit</th>
                <th>P&L %</th>
                <th>P&L $</th>
                <th>Reason</th>
                <th>Date</th>
              </tr>
            </thead>
            <tbody>
              {data.history?.map((t, i) => (
                <tr key={i}>
                  <td style={{ fontWeight: 600 }}>{t.symbol}</td>
                  <td>${t.entry_price?.toFixed(4)}</td>
                  <td>${t.exit_price?.toFixed(4)}</td>
                  <td className={t.pnl_pct >= 0 ? 'stat-value positive' : 'stat-value negative'} style={{ fontSize: '1rem' }}>
                    {t.pnl_pct > 0 ? '+' : ''}{t.pnl_pct.toFixed(2)}%
                  </td>
                  <td className={t.pnl_usd >= 0 ? 'stat-value positive' : 'stat-value negative'} style={{ fontSize: '1rem' }}>
                    {t.pnl_usd > 0 ? '+' : ''}${t.pnl_usd?.toFixed(2)}
                  </td>
                  <td><span className={`badge ${t.pnl_usd >= 0 ? 'long' : 'short'}`}>{t.reason}</span></td>
                  <td style={{ color: 'var(--text-muted)' }}>{t.exit_date}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      {!data.history?.length && <p className="empty-state">No closed trades in this paper session.</p>}
    </div>
  );
}

function SettingsView() {
  const request = React.useContext(ApiContext);
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => {
    request('/config').then(setData).catch(err => setError(err.message));
  }, [request]);
  if (error) return <p role="alert" className="api-error">{error}</p>;
  if (!data) return <p>Loading settings...</p>;
  const values = [
    ['Mode', data.TRADING_MODE], ['Starting capital', `$${data.CAPITAL_USD.toFixed(2)}`],
    ['Leverage', `${data.LEVERAGE}x`], ['Net TP target', `${(data.FUTURES_NET_TP_PCT * 100).toFixed(2)}%`],
    ['Stop loss', data.FUTURES_USE_SL ? 'Enabled' : 'Disabled'], ['Max hold', `${data.MAX_HOLD_DAYS} days`],
    ['Per trade', `${(data.PER_TRADE_PCT * 100).toFixed(2)}%`], ['Max open trades', data.MAX_OPEN_TRADES],
  ];
  return (
    <div className="animate-fade-in">
      <h2 style={{ marginBottom: '32px' }}>Current Settings</h2>
      <div className="table-section">
        <table className="data-table"><tbody>{values.map(([label, value]) => <tr key={label}><th scope="row">{label}</th><td>{value}</td></tr>)}</tbody></table>
      </div>
    </div>
  );
}

export default function Dashboard() {
  const [request, setRequest] = useState(null);
  const [error, setError] = useState('');
  const [signingIn, setSigningIn] = useState(false);
  const signIn = async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const fields = new FormData(form);
    setSigningIn(true);
    setError('');
    try {
      const base = new URL(API_URL, window.location.origin);
      const loopback = ['localhost', '127.0.0.1', '[::1]'].includes(base.hostname);
      if (base.protocol !== 'https:' && !loopback) throw new Error('HTTPS is required for sign-in.');
      const authorization = `Basic ${btoa(`${fields.get('username')}:${fields.get('password')}`)}`;
      const fetchApi = async (path) => {
        const response = await fetch(`${API_URL}${path}`, {
          headers: { Authorization: authorization }, credentials: 'omit', cache: 'no-store',
        });
        if (!response.ok) throw new Error(response.status === 401 ? 'Invalid username or password.' : `API unavailable (${response.status}).`);
        return response.json();
      };
      await fetchApi('/config');
      form.reset();
      setRequest(() => fetchApi);
    } catch (err) {
      setError(err.message);
    } finally {
      setSigningIn(false);
    }
  };
  if (!request) return (
    <main className="sign-in-page">
      <div className="sign-in-content">
        <Bot size={36} color="var(--primary)" aria-hidden="true" />
        <h1>TradingBot23</h1><h2>Paper Dashboard</h2>
        <form onSubmit={signIn}>
          <label htmlFor="username">Username</label>
          <input id="username" name="username" autoComplete="username" required disabled={signingIn} />
          <label htmlFor="password">Password</label>
          <input id="password" name="password" type="password" autoComplete="current-password" required disabled={signingIn} />
          <button className="btn-primary" type="submit" disabled={signingIn}><LogIn size={18} />{signingIn ? 'Signing In...' : 'Sign In'}</button>
          {error && <p role="alert" className="api-error">{error}</p>}
        </form>
      </div>
    </main>
  );
  return (
    <ApiContext.Provider value={request}>
    <div className="dashboard-layout">
      <Sidebar onLogout={() => { setRequest(null); setError(''); }} />
      <div className="main-content">
        <Routes>
          <Route path="/" element={<OpenTrades />} />
          <Route path="/history" element={<HistoryLog />} />
          <Route path="/settings" element={<SettingsView />} />
        </Routes>
      </div>
    </div>
    </ApiContext.Provider>
  );
}
