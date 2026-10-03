import type { ReactNode } from "react";

import { describeError } from "../lib/errors";

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="state state-loading" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: Error; onRetry?: () => void }) {
  const { title, detail } = describeError(error);
  return (
    <div className="state state-error" role="alert">
      <strong>{title}</strong>
      <p>{detail}</p>
      {onRetry && (
        <button type="button" className="btn btn-secondary" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="state state-empty">
      <strong>{title}</strong>
      {children && <p>{children}</p>}
    </div>
  );
}

/** Marks UI that will be powered by Phase 2 telemetry/WebSockets. */
export function Phase2Notice({ children }: { children: ReactNode }) {
  return (
    <div className="phase2" role="note">
      <span className="phase2-tag">Phase 2</span>
      <span>{children}</span>
    </div>
  );
}
