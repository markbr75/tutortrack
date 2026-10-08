import { Component, type ErrorInfo, type ReactNode } from "react";

import { Button } from "./Button";

export interface ErrorFallbackProps {
  title: string;
  retryLabel: string;
  detail?: string;
  onRetry?: () => void;
}

export function ErrorFallback({ title, detail, retryLabel, onRetry }: ErrorFallbackProps) {
  return (
    <div role="alert" className="mx-auto max-w-md rounded-md border border-border p-6 text-center">
      <h2 className="text-lg font-semibold">{title}</h2>
      {detail && <p className="mt-2 text-sm text-muted-foreground">{detail}</p>}
      {onRetry && (
        <Button variant="secondary" className="mt-4" onClick={onRetry}>
          {retryLabel}
        </Button>
      )}
    </div>
  );
}

interface BoundaryProps {
  fallback: (error: Error, reset: () => void) => ReactNode;
  onError?: (error: Error, info: ErrorInfo) => void;
  children: ReactNode;
}

/** Catches render errors so one broken widget never blanks the whole app. */
export class ErrorBoundary extends Component<BoundaryProps, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    this.props.onError?.(error, info);
  }

  reset = () => this.setState({ error: null });

  render() {
    return this.state.error
      ? this.props.fallback(this.state.error, this.reset)
      : this.props.children;
  }
}
