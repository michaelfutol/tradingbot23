import React from 'react';
import { Link } from 'react-router-dom';
import { Bot, TrendingUp, ShieldCheck, Activity } from 'lucide-react';

export default function LandingPage() {
  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      <header style={{ padding: '24px 48px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <Bot size={32} color="var(--primary)" />
          <h2 style={{ margin: 0 }}>TradingBot<span className="text-gradient">23</span></h2>
        </div>
        <nav style={{ display: 'flex', gap: '24px', alignItems: 'center' }}>
          <a href="#features" style={{ color: 'var(--text-muted)' }}>Features</a>
          <a href="#about" style={{ color: 'var(--text-muted)' }}>About</a>
          <Link to="/app" className="btn-secondary">Open Web Dashboard</Link>
        </nav>
      </header>

      <main style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', textAlign: 'center', padding: '64px 24px' }}>
        <div className="animate-fade-in" style={{ maxWidth: '800px' }}>
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: '8px', padding: '6px 16px', background: 'var(--bg-panel)', borderRadius: '20px', border: '1px solid var(--border-glass)', marginBottom: '32px' }}>
            <span style={{ width: '8px', height: '8px', borderRadius: '50%', background: 'var(--success)' }}></span>
            <span style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>Now Available on Web</span>
          </div>

          <h1 style={{ fontSize: '4.5rem', lineHeight: 1.1, marginBottom: '24px' }}>
            Automated <span className="text-gradient">Mean-Reversion</span> Trading
          </h1>

          <p style={{ fontSize: '1.2rem', color: 'var(--text-muted)', marginBottom: '48px', maxWidth: '600px', margin: '0 auto 48px' }}>
            A powerful, fully-automated crypto futures bot that buys the dip and secures the bag.
            Paper trade securely with cross-margin liquidation tracking.
          </p>

          <div style={{ display: 'flex', gap: '16px', justifyContent: 'center' }}>
            <a href="https://github.com/michaelfutol/tradingbot23/releases" className="btn-primary" style={{ padding: '16px 32px', fontSize: '1.1rem' }}>
              Download for Windows
            </a>
            <Link to="/app" className="btn-secondary" style={{ padding: '16px 32px', fontSize: '1.1rem' }}>
              Launch Web Dashboard
            </Link>
          </div>
        </div>

        <div className="stats-grid animate-fade-in delay-2" style={{ marginTop: '96px', width: '100%', maxWidth: '1000px', gridTemplateColumns: 'repeat(3, 1fr)' }}>
          <div className="glass-panel" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '16px' }}>
            <TrendingUp size={40} color="var(--primary)" />
            <h3>Data-Driven Strategy</h3>
            <p style={{ color: 'var(--text-muted)' }}>Targets top 50 large-cap coins dipping over 2%.</p>
          </div>
          <div className="glass-panel" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '16px' }}>
            <ShieldCheck size={40} color="var(--success)" />
            <h3>Risk Management</h3>
            <p style={{ color: 'var(--text-muted)' }}>Built-in crash protection and break-even trailing stops.</p>
          </div>
          <div className="glass-panel" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '16px' }}>
            <Activity size={40} color="var(--warning)" />
            <h3>Live Arbitrage</h3>
            <p style={{ color: 'var(--text-muted)' }}>Real-time USDT/PHP P2P route sizing and spread monitor.</p>
          </div>
        </div>
      </main>

      <footer style={{ padding: '32px', textAlign: 'center', borderTop: '1px solid var(--border-glass)' }}>
        <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem' }}>
          &copy; 2026 FutolTech | Educational purposes only. Not financial advice.
        </p>
      </footer>
    </div>
  );
}
