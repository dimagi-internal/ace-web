import { Outlet } from "react-router-dom";

import { ThemeProvider } from "@/components/ThemeProvider";
import { Toaster } from "@/components/ui/sonner";

export function App() {
  return (
    <ThemeProvider>
      <Outlet />
      <Toaster />
    </ThemeProvider>
  );
}
