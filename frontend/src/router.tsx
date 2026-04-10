import { createBrowserRouter } from "react-router-dom";

import { App } from "./App";
import { DriveReconnectGuard } from "./components/opps/DriveReconnectGuard";
import HealthPage from "./pages/HealthPage";
import HomePage from "./pages/HomePage";
import { ChatPage } from "./pages/ChatPage";
import { ChatRedirectPage } from "./pages/ChatRedirectPage";
import { AuthCliPage } from "./pages/AuthCliPage";
import LibraryPage from "./pages/LibraryPage";
import OppListPage from "./pages/OppListPage";
import OppWorkbenchPage from "./pages/OppWorkbenchPage";
import OppComparePage from "./pages/OppComparePage";
import SettingsPage from "./pages/SettingsPage";

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
        { path: "library", element: <LibraryPage /> },
        { path: "settings", element: <SettingsPage /> },
        {
          path: "opps",
          element: (
            <DriveReconnectGuard>
              <OppListPage />
            </DriveReconnectGuard>
          ),
        },
        {
          path: "opps/:slug",
          element: (
            <DriveReconnectGuard>
              <OppWorkbenchPage />
            </DriveReconnectGuard>
          ),
        },
        {
          path: "opps/:slug/runs/:runId",
          element: (
            <DriveReconnectGuard>
              <OppWorkbenchPage />
            </DriveReconnectGuard>
          ),
        },
        {
          path: "opps/:slug/runs/:runId/steps/:skill",
          element: (
            <DriveReconnectGuard>
              <OppWorkbenchPage />
            </DriveReconnectGuard>
          ),
        },
        {
          path: "opps/:slug/compare",
          element: (
            <DriveReconnectGuard>
              <OppComparePage />
            </DriveReconnectGuard>
          ),
        },
      ],
    },
  ],
  { basename: "/ace" },
);
