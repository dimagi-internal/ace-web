import { Navigate, createBrowserRouter } from "react-router-dom";

import { App } from "./App";
import { PublicLayout } from "./components/PublicLayout";
import { AuthCliPage } from "./pages/AuthCliPage";
import { ChatPage } from "./pages/ChatPage";
import { ChatRedirectPage } from "./pages/ChatRedirectPage";
import InviteAcceptPage from "./pages/InviteAcceptPage";
import MediaLibraryPage from "./pages/MediaLibraryPage";
import { NoWorkspaceRedirect } from "./pages/NoWorkspaceRedirect";
import OppComparePage from "./pages/OppComparePage";
import OppListPage from "./pages/OppListPage";
import OppSummaryPage from "./pages/OppSummaryPage";
import OppWorkbenchPage from "./pages/OppWorkbenchPage";
import { SessionStructurePage } from "./pages/SessionStructurePage";
import SessionsPage from "./pages/SessionsPage";
import SettingsPage from "./pages/SettingsPage";
import ShareViewPage from "./pages/ShareViewPage";
import SystemPage from "./pages/SystemPage";
import VideoExplorerPage from "./pages/VideoExplorerPage";
import VideosListPage from "./pages/VideosListPage";
import WelcomePage from "./pages/WelcomePage";
import WorkspaceActivityPage from "./pages/WorkspaceActivityPage";
import WorkspaceSettingsPage from "./pages/WorkspaceSettingsPage";

export const router = createBrowserRouter(
  [
    // Public, unauthenticated routes (no TopNav — those make authed API
    // calls that would bounce anonymous viewers to /auth/login).
    {
      element: <PublicLayout />,
      children: [
        {
          path: "/opps/:workspace/:slug/runs/:runId/summary",
          element: <OppSummaryPage />,
        },
      ],
    },
    {
      path: "/",
      element: <App />,
      children: [
        // Workspace-scoped surface
        {
          path: "w/:workspaceSlug",
          children: [
            { index: true, element: <Navigate to="opps" replace /> },
            { path: "activity", element: <WorkspaceActivityPage /> },
            { path: "opps", element: <OppListPage /> },
            {
              path: "opps/compare/:slugA/:slugB",
              element: <OppComparePage />,
            },
            { path: "opps/:slug", element: <OppWorkbenchPage /> },
            { path: "opps/:slug/runs/:runId", element: <OppWorkbenchPage /> },
            {
              path: "opps/:slug/runs/:runId/steps/:skill",
              element: <OppWorkbenchPage />,
            },
            { path: "sessions", element: <SessionsPage /> },
            { path: "videos", element: <VideosListPage /> },
            { path: "videos/library", element: <MediaLibraryPage /> },
            { path: "videos/:programSlug", element: <VideoExplorerPage /> },
            {
              path: "videos/:programSlug/runs/:runId",
              element: <VideoExplorerPage />,
            },
            { path: "chat", element: <ChatRedirectPage /> },
            { path: "chat/:slug", element: <ChatPage /> },
            { path: "chat/:slug/structure", element: <SessionStructurePage /> },
            { path: "workspace-settings", element: <WorkspaceSettingsPage /> },
          ],
        },

        // User-level (workspace-agnostic)
        { path: "welcome", element: <WelcomePage /> },
        { path: "invite/:token", element: <InviteAcceptPage /> },
        { path: "settings", element: <SettingsPage /> },
        { path: "system", element: <SystemPage /> },
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
