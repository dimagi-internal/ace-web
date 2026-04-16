import { createBrowserRouter } from "react-router-dom";

import { App } from "./App";
import HealthPage from "./pages/HealthPage";
import HomePage from "./pages/HomePage";
import { ChatPage } from "./pages/ChatPage";
import { ChatRedirectPage } from "./pages/ChatRedirectPage";
import { AuthCliPage } from "./pages/AuthCliPage";
import SessionsPage from "./pages/SessionsPage";
import OppListPage from "./pages/OppListPage";
import OppWorkbenchPage from "./pages/OppWorkbenchPage";
import OppComparePage from "./pages/OppComparePage";
import SettingsPage from "./pages/SettingsPage";
import ShareViewPage from "./pages/ShareViewPage";
import SystemPage from "./pages/SystemPage";

export const router = createBrowserRouter(
  [
    {
      path: "/",
      element: <App />,
      children: [
        { index: true, element: <HomePage /> },
        { path: "health", element: <HealthPage /> },
        { path: "chat", element: <ChatRedirectPage /> },
        { path: "chat/:slug", element: <ChatPage /> },
        { path: "auth/cli", element: <AuthCliPage /> },
        { path: "sessions", element: <SessionsPage /> },
        { path: "settings", element: <SettingsPage /> },
        { path: "opps", element: <OppListPage /> },
        { path: "opps/:slug", element: <OppWorkbenchPage /> },
        { path: "opps/:slug/runs/:runId", element: <OppWorkbenchPage /> },
        {
          path: "opps/:slug/runs/:runId/steps/:skill",
          element: <OppWorkbenchPage />,
        },
        { path: "opps/:slug/compare", element: <OppComparePage /> },
        { path: "system", element: <SystemPage /> },
        { path: "share/:token", element: <ShareViewPage /> },
      ],
    },
  ],
  { basename: "/ace" },
);
