import { createBrowserRouter, RouterProvider } from "react-router-dom"
import HomePage from "./pages/HomePage"
import HealthPage from "./pages/HealthPage"

const router = createBrowserRouter([
  { path: "/", element: <HomePage /> },
  { path: "/health-check", element: <HealthPage /> },
])

export function Router() {
  return <RouterProvider router={router} />
}
