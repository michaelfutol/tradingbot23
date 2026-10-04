import React, { useState, useEffect, useCallback } from 'react';
import { Link, Routes, Route, useLocation } from 'react-router-dom';
import { LayoutDashboard, History, Settings, RefreshCw, LogOut, LogIn,
  ArrowUpRight, Clock3, Info, ShieldCheck } from 'lucide-react';
import Brand from './Brand';

const API_URL = (import.meta.env.VITE_API_URL || '/api').replace(/\/$/, '');
const ApiContext = React.createContext(null);
const money = value => Number.isFinite(value) ? new Intl.NumberFormat('en-US',
  { style: 'currency', currency: 'USD', maximumFractionDigits: 2 }).format(value) : '--';
const price = value => Number.isFinite(value) ? new Intl.NumberFormat('en-US',
  { style: 'currency', currency: 'USD', minimumFractionDigits: 4,
    maximumFractionDigits: Math.abs(value) < 0.01 ? 8 : 4 }).format(value) : '--';
const percent = value => Number.isFinite(value) ? `${value > 0 ? '+' : ''}${value.toFixed(2)}%` : '--';
const tone = value => value > 0 ? 'positive' : value < 0 ? 'negative' : '';
const date = value => value ? new Date(value).toLocaleString('en-US',
  { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '--';

function useResource(path) {
  const request = React.useContext(ApiContext);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const refresh = useCallback(async () => {
    setLoading(true);
    setError('');
    try { setData(await request(path)); }
    catch (err) { setError(err.message); }
    finally { setLoading(false); }
  }, [request, path]);
  useEffect(() => { refresh(); }, [refresh]);
  return { data, loading, error, refresh };
}

function Sidebar({ onLogout }) {
  const location = useLocation();
  const items = [
    { path: '/app', icon: LayoutDashboard, label: 'Overview' },
    { path: '/app/history', icon: History, label: 'History' },
    { path: '/app/settings', icon: Settings, label: 'Settings' },
  ];
  return (
    <aside className="sidebar">
      <div className="sidebar-brand"><Brand /><span className="workspace-label">Paper workspace</span></div>
      <nav className="workspace-nav" aria-label="Workspace">
        {items.map(item => <Link key={item.path} to={item.path}
          aria-current={location.pathname === item.path ? 'page' : undefined}
          className={`nav-item ${location.pathname === item.path ? 'active' : ''}`}>
          <item.icon size={19} aria-hidden="true" /><span>{item.label}</span>
        </Link>)}
      </nav>
      <div className="sidebar-footer">
        <Link to="/about" className="nav-item" title="About Trade23" aria-label="About Trade23">
          <Info size={18} /><span>About Trade23</span>
        </Link>
        <button className="nav-item sign-out" onClick={onLogout} title="Sign out" aria-label="Sign out">
          <LogOut size={18} /><span>Sign out</span>
        </button>
        <span className="footer-brand">FutolTech</span>
      </div>
    </aside>
  );
}

function Heading({ title, resource, label = 'Paper account' }) {
  return <header className="view-heading"><div><p className="eyebrow">{label}</p><h1>{title}</h1></div>
    <button className="icon-button" title="Refresh account snapshot" aria-label="Refresh account snapshot"
      onClick={resource.refresh} disabled={resource.loading}>
      <RefreshCw size={18} className={resource.loading ? 'spin' : ''} />
    </button></header>;
}

function ResourceState({ resource }) {
  if (resource.error) return <p role="alert" className="api-error">{resource.error}</p>;
  if (!resource.data) return <p className="empty-state" role="status">Loading account...</p>;
  return null;
}

function Metric({ label, value, color = '', title }) {
  return <div className="metric" title={title}><dt>{label}</dt><dd className={color}>{value}</dd></div>;
}

function TradeCard({ trade, closed = false }) {
  return <article className="trade-card">
    <div className="trade-card-heading">
      <div className="trade-symbol"><span className="coin-mark" aria-hidden="true">{trade.symbol.slice(0, 1)}</span>
        <div><h3>{trade.symbol}<span className="quote-currency"> / USDT</span></h3>
          <span className="trade-meta">{trade.leverage}x {closed ? ` / ${trade.reason.replaceAll('_', ' ')}` : 'cross'}</span></div>
      </div>
      <div className={`trade-return ${tone(trade.pnl_usd)}`}><strong>{money(trade.pnl_usd)}</strong><span>{percent(trade.pnl_pct)}</span></div>
    </div>
    <dl className="trade-details">
      <div><dt>Entry</dt><dd>{price(trade.entry_price)}</dd></div>
      <div><dt>{closed ? 'Exit' : 'Cached mark'}</dt><dd>{price(closed ? trade.exit_price : trade.last_known_price)}</dd></div>
      {!closed && <div><dt>Margin</dt><dd>{money(trade.margin_used)}</dd></div>}
      {!closed && <div><dt>Net TP</dt><dd>{price(trade.tp_price)}</dd></div>}
    </dl>
    {closed && <p className="trade-meta">{date(trade.exit_date)}</p>}
  </article>;
}

function OpenTrades() {
  const resource = useResource('/status');
  const data = resource.data;
  const positions = data?.open_positions || [];
  return <>
    <Heading title="Overview" resource={resource} />
    <ResourceState resource={resource} />
    {data && <>
      <dl className="account-metrics">
        <Metric label="Net equity estimate" value={money(data.estimated_net_equity)}
          title="Cached marked equity after modeled exit costs. Not an executable or exchange-exact balance." />
        <Metric label="Free cash" value={money(data.cash_balance)} />
        <Metric label="Realized net P&L" value={money(data.stats?.total_net_pnl_usd)} color={tone(data.stats?.total_net_pnl_usd)} />
        <Metric label="Win rate" value={`${(data.stats?.win_rate || 0).toFixed(1)}%`}
          title="Positive net closed trades only. Open losses are excluded." />
      </dl>
      <div className="account-context">
        <span>Marked equity <strong>{money(data.portfolio_value)}</strong></span>
        <span>Expectancy / trade <strong className={tone(data.stats?.expectancy_usd)}>{money(data.stats?.expectancy_usd)}</strong></span>
        <span title="This is the account snapshot time, not proof that cached prices are fresh."><Clock3 size={14} />Snapshot {date(data.as_of)}</span>
      </div>
      <section className="table-section">
        <div className="section-heading"><h2>Open positions</h2><span className="muted">{positions.length} open</span></div>
        {positions.length ? <>
          <div className="table-scroll desktop-trades"><table className="data-table">
            <thead><tr><th>Symbol</th><th>Entry lev.</th><th>Margin</th><th>Entry</th><th>Cached mark</th><th>Net P&L %</th><th>Net P&L $</th></tr></thead>
            <tbody>{positions.map((pos, i) => <tr key={`${pos.symbol}-${i}`}>
              <td className="symbol-cell">{pos.symbol}<span className="quote-currency"> / USDT</span></td>
              <td>{pos.leverage}x</td><td>{money(pos.margin_used)}</td><td>{price(pos.entry_price)}</td><td>{price(pos.last_known_price)}</td>
              <td className={tone(pos.pnl_pct)}>{percent(pos.pnl_pct)}</td><td className={tone(pos.pnl_usd)}>{money(pos.pnl_usd)}</td>
            </tr>)}</tbody>
          </table></div>
          <div className="mobile-trades">{positions.map((pos, i) => <TradeCard key={`${pos.symbol}-${i}`} trade={pos} />)}</div>
        </> : <div className="empty-state"><LayoutDashboard size={22} /><p>No open positions</p></div>}
      </section>
    </>}
  </>;
}

function HistoryLog() {
  const resource = useResource('/history');
  const trades = resource.data?.history || [];
  return <>
    <Heading title="Trade history" resource={resource} />
    <ResourceState resource={resource} />
    {resource.data && <>
      <dl className="account-metrics history-metrics">
        <Metric label="Closed trades" value={resource.data.stats?.total_trades || 0} />
        <Metric label="Realized net P&L" value={money(resource.data.stats?.total_net_pnl_usd)} color={tone(resource.data.stats?.total_net_pnl_usd)} />
        <Metric label="Expectancy / trade" value={money(resource.data.stats?.expectancy_usd)} />
      </dl>
      <section className="table-section">
        <div className="section-heading"><h2>Closed positions</h2><span className="muted">Latest {trades.length}</span></div>
        {trades.length ? <>
          <div className="table-scroll desktop-trades"><table className="data-table">
            <thead><tr><th>Symbol</th><th>Entry</th><th>Exit</th><th>Net P&L %</th><th>Net P&L $</th><th>Reason</th><th>Closed</th></tr></thead>
            <tbody>{trades.map((trade, i) => <tr key={`${trade.symbol}-${i}`}>
              <td className="symbol-cell">{trade.symbol}</td><td>{price(trade.entry_price)}</td><td>{price(trade.exit_price)}</td>
              <td className={tone(trade.pnl_pct)}>{percent(trade.pnl_pct)}</td><td className={tone(trade.pnl_usd)}>{money(trade.pnl_usd)}</td>
              <td><span className="reason-tag">{trade.reason.replaceAll('_', ' ')}</span></td><td className="muted">{date(trade.exit_date)}</td>
            </tr>)}</tbody>
          </table></div>
          <div className="mobile-trades">{trades.map((trade, i) => <TradeCard key={`${trade.symbol}-${i}`} trade={trade} closed />)}</div>
        </> : <div className="empty-state"><History size={22} /><p>No closed trades</p></div>}
      </section>
    </>}
  </>;
}

function SettingsView() {
  const resource = useResource('/config');
  const data = resource.data;
  const values = data ? [
    ['Mode', data.TRADING_MODE], ['Capital (USD)', money(data.CAPITAL_USD)],
    ['Entry leverage', `${data.LEVERAGE}x`], ['Net TP target', percent(data.FUTURES_NET_TP_PCT * 100)],
    ['Stop loss', data.FUTURES_USE_SL ? 'Enabled' : 'Disabled'], ['Max hold', `${data.MAX_HOLD_DAYS} days`],
    ['Per trade', percent(data.PER_TRADE_PCT * 100)], ['Max open trades', data.MAX_OPEN_TRADES],
  ] : [];
  return <>
    <Heading title="Account settings" resource={resource} label="Read-only snapshot" />
    <ResourceState resource={resource} />
    {data && <dl className="settings-list">{values.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>}
  </>;
}

export default function Dashboard() {
  const [request, setRequest] = useState(null);
  const [error, setError] = useState('');
  const [signingIn, setSigningIn] = useState(false);
  const signIn = async event => {
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
      const fetchApi = async path => {
        const response = await fetch(`${API_URL}${path}`, {
          headers: { Authorization: authorization }, credentials: 'omit', cache: 'no-store',
        });
        if (!response.ok) throw new Error(response.status === 401 ? 'Invalid username or password.' : `API unavailable (${response.status}).`);
        return response.json();
      };
      await fetchApi('/config');
      form.reset();
      setRequest(() => fetchApi);
    } catch (err) { setError(err.message); }
    finally { setSigningIn(false); }
  };
  if (!request) return <main className="sign-in-page">
    <header className="sign-in-brand"><Brand /><span className="paper-indicator"><ShieldCheck size={15} />Paper</span></header>
    <div className="sign-in-content">
      <p className="eyebrow">Private workspace</p><h1>Sign in</h1>
      <form onSubmit={signIn}>
        <label htmlFor="username">Username</label>
        <input id="username" name="username" autoComplete="username" required disabled={signingIn} />
        <label htmlFor="password">Password</label>
        <input id="password" name="password" type="password" autoComplete="current-password" required disabled={signingIn} />
        <button className="btn-primary" type="submit" disabled={signingIn}><LogIn size={18} />{signingIn ? 'Signing in...' : 'Sign in'}</button>
        {error && <p role="alert" className="api-error">{error}</p>}
      </form>
      <Link to="/about" className="about-link">Trade23 <ArrowUpRight size={16} /></Link>
    </div>
    <footer className="sign-in-footer">FutolTech</footer>
  </main>;
  return <ApiContext.Provider value={request}>
    <div className="dashboard-layout">
      <Sidebar onLogout={() => { setRequest(null); setError(''); }} />
      <main className="main-content">
        <div className="workspace-topline"><span><ShieldCheck size={15} />Futures paper</span><span className="muted">USD account</span></div>
        <Routes><Route path="/" element={<OpenTrades />} /><Route path="/history" element={<HistoryLog />} />
          <Route path="/settings" element={<SettingsView />} /></Routes>
      </main>
    </div>
  </ApiContext.Provider>;
}
