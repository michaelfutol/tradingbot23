import { Link } from 'react-router-dom';
import { ArrowUpRight, Download } from 'lucide-react';
import Brand from './Brand';

export default function LandingPage() {
  return <div className="product-page">
    <header className="product-nav"><Brand compact />
      <Link to="/app" className="btn-secondary">Workspace <ArrowUpRight size={16} /></Link>
    </header>
    <main className="product-main">
      <header className="product-heading">
        <div><p className="eyebrow">Futures paper workspace</p><h1>Trade23</h1></div>
        <a href="https://github.com/michaelfutol/tradingbot23/actions/workflows/build.yml" className="btn-primary">
          <Download size={17} />Desktop builds
        </a>
      </header>
      <figure className="product-preview">
        <picture>
          <source media="(max-width: 720px)" srcSet="/workspace-mobile.png" />
          <img src="/workspace-desktop.png" alt="Trade23 paper portfolio with net equity, open positions and trade history navigation" width="1440" height="1000" />
        </picture>
        <figcaption>Offline paper account preview. Not live market prices.</figcaption>
      </figure>
    </main>
    <footer className="product-footer"><span>FutolTech</span><span>Personal paper testing. No live orders.</span></footer>
  </div>;
}
