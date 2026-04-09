import { Link } from "react-router-dom";

import { useCliAuthStatus } from "../hooks/useCliAuthStatus";

export function CliAuthBanner() {
  const authenticated = useCliAuthStatus();
  if (authenticated !== false) return null;
  return (
    <div className="border-b border-amber-300 bg-amber-50 px-4 py-2 text-sm text-amber-900">
      Claude CLI is not connected.{" "}
      <Link to="/auth/cli" className="font-semibold underline">
        Connect now →
      </Link>
    </div>
  );
}
