import { LockKeyhole, ShieldCheck } from 'lucide-react'
import { SignalField } from './SignalField'

export function LoginBoundary({ mode, detail }: { mode: 'loading' | 'error'; detail?: string }) {
  const loading = mode === 'loading'
  return (
    <main className="auth-boundary">
      <div className="auth-art"><SignalField /></div>
      <section className="auth-panel" aria-live="polite">
        <div className="auth-brand"><span className="brand-mark">LG</span><div><strong>LGHS Fleet</strong><span>Operations console</span></div></div>
        <div className="auth-icon" aria-hidden="true">{loading ? <ShieldCheck /> : <LockKeyhole />}</div>
        <h1>{loading ? 'Verifying access' : 'Fleet access unavailable'}</h1>
        <p>{loading ? 'Checking your Cloudflare Access identity and controller session.' : (detail || 'The controller could not verify this session.')}</p>
        {!loading && <a className="button primary auth-action" href="/cdn-cgi/access/logout">Sign in again</a>}
        <div className="auth-footnote">Protected by Cloudflare Access · LGHS authorization is enforced at the controller</div>
      </section>
    </main>
  )
}
