// Section E: every panel gets the same four honest states, in one place
// rather than reimplemented per-panel. 'ready' renders children; everything
// else replaces them with a real, specific message — never a bare spinner.
import type { ReactNode } from 'react';

export type Status = 'idle' | 'loading' | 'ready' | 'empty' | 'error';

interface Props {
  status: Status;
  progress?: { current: number; total: number; message: string } | null;
  idleMessage?: string;
  emptyMessage?: string;
  errorMessage?: string | null;
  degradedMessage?: string | null;
  children?: ReactNode;
}

export default function PanelState({ status, progress, idleMessage, emptyMessage, errorMessage, degradedMessage, children }: Props) {
  if (status === 'ready') {
    return (
      <>
        {degradedMessage && <div className="panel-state panel-state--degraded">{degradedMessage}</div>}
        {children}
      </>
    );
  }
  if (status === 'loading') {
    const pct = progress && progress.total > 0 ? Math.round((progress.current / progress.total) * 100) : null;
    return (
      <div className="panel-state panel-state--loading">
        <div className="panel-state__bar"><div className="panel-state__bar-fill" style={{ width: `${pct ?? 0}%` }} /></div>
        <div className="num panel-state__label">{progress?.message ?? 'Working…'}{pct !== null ? ` (${pct}%)` : ''}</div>
      </div>
    );
  }
  if (status === 'empty') {
    return <div className="panel-state panel-state--empty">{emptyMessage ?? 'Nothing here yet.'}</div>;
  }
  if (status === 'error') {
    return <div className="panel-state panel-state--error">{errorMessage ?? 'Something failed.'}</div>;
  }
  return <div className="panel-state panel-state--idle">{idleMessage ?? 'Not started yet.'}</div>;
}
