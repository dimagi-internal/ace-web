import { useEffect, useState } from "react"
import { api } from "../api/client"

export default function HealthPage() {
  const [status, setStatus] = useState<string>("loading...")
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .health()
      .then((r) => setStatus(r.status))
      .catch((e) => setError(String(e)))
  }, [])

  return (
    <div className="mx-auto max-w-4xl p-12">
      <h1 className="text-2xl font-semibold">Backend health</h1>
      {error ? (
        <p className="mt-4 text-red-600">Error: {error}</p>
      ) : (
        <p className="mt-4">Status: <span className="font-mono">{status}</span></p>
      )}
    </div>
  )
}
