import { Component, type ReactNode } from "react";

import { DriveReconnectRequired } from "../../api/types";

interface Props {
  children: ReactNode;
}

interface State {
  reconnectUrl: string | null;
}

/**
 * Error boundary that catches DriveReconnectRequired errors from child
 * components and redirects the user to the Drive OAuth start URL.
 *
 * Why an error boundary rather than per-call try/catch: the opps pages
 * all read from the api/opps.ts client inside useEffect hooks, and a
 * single boundary at the route level saves every page from repeating
 * the same catch block.
 */
export class DriveReconnectGuard extends Component<Props, State> {
  state: State = { reconnectUrl: null };

  static getDerivedStateFromError(error: unknown): State | null {
    if (error instanceof DriveReconnectRequired) {
      return { reconnectUrl: error.reconnectUrl };
    }
    return null;
  }

  componentDidCatch(error: unknown) {
    if (!(error instanceof DriveReconnectRequired)) {
      // Rethrow non-reconnect errors so the default boundary handles them.
      throw error;
    }
  }

  componentDidUpdate() {
    if (this.state.reconnectUrl) {
      window.location.href = this.state.reconnectUrl;
    }
  }

  render() {
    if (this.state.reconnectUrl) {
      return (
        <div className="p-6 text-muted-foreground">
          Redirecting to Google to connect Drive access…
        </div>
      );
    }
    return this.props.children;
  }
}
