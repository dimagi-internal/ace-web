import { Outlet } from "react-router-dom";

import { ThemeProvider } from "@/components/ThemeProvider";

/**
 * Layout for public, unauthenticated pages. Provides theme context but
 * deliberately omits TopNav and any workspace-aware nav — the latter
 * fires authenticated API calls that bounce anonymous users to /auth/login.
 */
export function PublicLayout() {
  return (
    <ThemeProvider>
      <Outlet />
    </ThemeProvider>
  );
}
