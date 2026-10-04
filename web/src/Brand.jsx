export default function Brand({ compact = false }) {
  return (
    <div className={`brand${compact ? ' brand-compact' : ''}`}>
      <img src="/trade23-mark.svg" alt="" width="40" height="40" />
      <span>Trade<span className="brand-number">23</span></span>
    </div>
  );
}
