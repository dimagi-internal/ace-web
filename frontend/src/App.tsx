import { Outlet } from "react-router-dom";

import { ThemeProvider } from "@/components/ThemeProvider";
import { TopNav } from "@/components/TopNav";
import { Toaster } from "canopy-ui/ui";

export function App() {
  return (
    <ThemeProvider>
      <div className="flex h-screen flex-col">
        <TopNav />
        {/* Default scroll region for pages: any page that overflows
            the remaining viewport gets a scrollbar for free. Pages
            that need their own scroll layout (chat, structure tree,
            mobile emulator) can still wrap themselves in `h-full` +
            a custom overflow region — `h-full` resolves against this
            fixed flex-1 box. Historically this was `overflow-hidden`,
            which silently clipped content and forced every new page
            author to remember an internal scroll wrapper. */}
        <div className="flex-1 overflow-y-auto">
          <Outlet />
        </div>
      </div>
      <Toaster />
    </ThemeProvider>
  );
}
