export default function WelcomePage() {
  return (
    <div className="mx-auto max-w-xl px-6 py-12 text-center">
      <h1 className="text-2xl font-semibold text-foreground">Welcome to ACE</h1>
      <p className="mt-3 text-muted-foreground">
        You don't have a workspace yet. Workspace self-creation lands in
        Phase B; for now, ask an admin to add you to an existing workspace.
      </p>
    </div>
  );
}
