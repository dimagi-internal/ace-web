import { Navigate, createBrowserRouter } from "react-router-dom";

import { App } from "./App";
import { AuthCliPage } from "./pages/AuthCliPage";
import { ChatPage } from "./pages/ChatPage";
import { ChatRedirectPage } from "./pages/ChatRedirectPage";
import HealthPage from "./pages/HealthPage";
import InviteAcceptPage from "./pages/InviteAcceptPage";
import { NoWorkspaceRedirect } from "./pages/NoWorkspaceRedirect";
import OppListPage from "./pages/OppListPage";
import OppWorkbenchPage from "./pages/OppWorkbenchPage";
import SessionsPage from "./pages/SessionsPage";
import SettingsPage from "./pages/SettingsPage";
import ShareViewPage from "./pages/ShareViewPage";
import SystemPage from "./pages/SystemPage";
import WelcomePage from "./pages/WelcomePage";
import WorkspaceSettingsPage from "./pages/WorkspaceSettingsPage";

export const router = createBrowserRouter(
  [
    {
      path: "/",
      element: <App />,
      children: [
        // Workspace-scoped surface
        {
          path: "w/:workspaceSlug",
          children: [
            { index: true, element: <Navigate to="opps" replace /> },
            { path: "opps", element: <OppListPage /> },
            { path: "opps/:slug", element: <OppWorkbenchPage /> },
            { path: "opps/:slug/runs/:runId", element: <OppWorkbenchPage /> },
            {
              path: "opps/:slug/runs/:runId/steps/:skill",
              element: <OppWorkbenchPage />,
            },
            { path: "sessions", element: <SessionsPage /> },
            { path: "chat", element: <ChatRedirectPage /> },
            { path: "chat/:slug", element: <ChatPage /> },
            { path: "workspace-settings", element: <WorkspaceSettingsPage /> },
          ],
        },

        // User-level (workspace-agnostic)
        { path: "welcome", element: <WelcomePage /> },
        { path: "invite/:token", element: <InviteAcceptPage /> },
        { path: "settings", element: <SettingsPage /> },
        { path: "system", element: <SystemPage /> },
        { path: "health", element: <HealthPage /> },
        { path: "auth/cli", element: <AuthCliPage /> },
        { path: "share/:token", element: <ShareViewPage /> },

        // Legacy redirects: bare /opps, /sessions, /chat — resolve to the
        // user's first workspace (or /welcome if none). Deep links with
        // a slug substitute the slug into the redirect.
        { index: true, element: <NoWorkspaceRedirect subPath="opps" /> },
        { path: "opps", element: <NoWorkspaceRedirect subPath="opps" /> },
        { path: "opps/:slug", element: <NoWorkspaceRedirect subPath="opps/:slug" /> },
        { path: "sessions", element: <NoWorkspaceRedirect subPath="sessions" /> },
        { path: "chat", element: <NoWorkspaceRedirect subPath="chat" /> },
        { path: "chat/:slug", element: <NoWorkspaceRedirect subPath="chat/:slug" /> },
      ],
    },
  ],
  { basename: "/ace" },
);
