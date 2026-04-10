import { Link } from "react-router-dom"

export default function HomePage() {
  return (
    <div className="mx-auto max-w-4xl p-12">
      <h1 className="text-3xl font-semibold">ACE Web Harness</h1>
      <p className="mt-4 text-muted-foreground">
        Foundation shell. Chat and transcripts arrive in Plan 1B.
      </p>
      <Link to="/health-check" className="mt-6 inline-block text-primary underline">
        Check backend health
      </Link>
    </div>
  )
}
