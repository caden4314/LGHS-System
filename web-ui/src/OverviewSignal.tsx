import { Radio, Router, ShieldCheck } from 'lucide-react'
import { SignalField } from './SignalField'

export function OverviewSignal({ online, total, critical }: { online: number; total: number; critical: number }) {
  return (
    <section className="overview-signal" aria-label="Fleet communications status">
      <div className="overview-signal-copy">
        <span className="overview-signal-kicker"><Radio aria-hidden="true" /> Control plane</span>
        <strong>{critical ? `${critical} device${critical === 1 ? '' : 's'} need attention` : 'Fleet communications nominal'}</strong>
        <span>{online}/{total} devices are reporting through the LGHS control plane.</span>
        <div className="overview-signal-facts">
          <span><Router aria-hidden="true" /> HTTPS telemetry</span>
          <span><ShieldCheck aria-hidden="true" /> Per-device identity</span>
        </div>
      </div>
      <div className="overview-signal-art"><SignalField compact /></div>
    </section>
  )
}
