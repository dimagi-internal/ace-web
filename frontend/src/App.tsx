import { Outlet } from "react-router-dom";

import { ThemeProvider } from "@/components/ThemeProvider";
import { TopNav } from "@/components/TopNav";
import { Toaster } from "@/components/ui/sonner";

export function App() {
  return (
    <ThemeProvider>
      <div className="flex h-screen flex-col">
        <TopNav />
        <div className="flex-1 overflow-hidden">
          <Outlet />
        </div>
      </div>
      <Toaster />
    </ThemeProvider>
  );
}
