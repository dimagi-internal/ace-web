import { createBrowserRouter } from "react-router-dom";

import { App } from "./App";
import HealthPage from "./pages/HealthPage";
import HomePage from "./pages/HomePage";
import { ChatPage } from "./pages/ChatPage";
import { ChatRedirectPage } from "./pages/ChatRedirectPage";
import { AuthCliPage } from "./pages/AuthCliPage";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <App />,
    children: [
      { index: true, element: <HomePage /> },
      { path: "health", element: <HealthPage /> },
      { path: "chat", element: <ChatRedirectPage /> },
      { path: "chat/:slug", element: <ChatPage /> },
      { path: "auth/cli", element: <AuthCliPage /> },
    ],
  },
]);
