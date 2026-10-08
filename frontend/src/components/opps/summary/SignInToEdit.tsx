import { LogIn } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * Where a write control would be, for a viewer who may not write.
 *
 * Changing, confirming and commenting on decisions need a signed-in
 * ace-web account that is a member of the workspace (Jonathan,
 * 2026-10-03: "no anonymous editing at all"); the API refuses anyone else
 * with 401/403. Everyone can still READ the page, so a non-member gets a
 * clear way in rather than a control that would fail.
 *
 * The login page sends a signed-in user back via `next`, so this returns
 * the reader to the exact tab they were on.
 */
export function signInHref(): string {
  const base = (import.meta.env.BASE_URL ?? "/").replace(/\/$/, "");
  const here =
    typeof window !== "undefined"
      ? `${window.location.pathname}${window.location.search}`
      : `${base}/`;
  return `${base}/auth/login/?next=${encodeURIComponent(here)}`;
}

export function SignInToEdit({
  className,
  children = "Sign in to edit",
}: {
  className?: string;
  children?: React.ReactNode;
}) {
  return (
    <a
      href={signInHref()}
      className={cn(
        "inline-flex items-center gap-1.5 text-[13px] font-medium text-foreground underline-offset-4 hover:underline",
        className,
      )}
      title="Changing, confirming and commenting need an account in this workspace"
    >
      <LogIn size={14} aria-hidden />
      {children}
    </a>
  );
}

/** The server's 403 copy for a member whose role may not write decisions. */
export const READ_ONLY_ROLE_COPY = "Your role in this workspace can view but not change decisions.";

/**
 * Where a write control would be, for a reader who may not write: a
 * read-only MEMBER (a `viewer`) is told why — signing in again would not
 * help them — and anyone else is offered sign-in.
 */
export function CannotWrite({
  readOnlyMember,
  className,
  children,
}: {
  /** Signed in as a member whose role cannot write (`decisions.write`). */
  readOnlyMember: boolean;
  className?: string;
  /** The sign-in link's text, for a non-member. */
  children?: React.ReactNode;
}) {
  if (readOnlyMember) {
    return (
      <p
        className={cn("text-[13px] text-muted-foreground", className)}
        data-testid="read-only-role"
      >
        {READ_ONLY_ROLE_COPY}
      </p>
    );
  }
  return <SignInToEdit className={className}>{children}</SignInToEdit>;
}
