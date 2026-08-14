/**
 * Who a partner says they are, remembered locally.
 *
 * The public run summary has no login and a partner cannot self-serve
 * one. Requiring an account is a barrier in front of speculative work
 * whose whole point is that engaging with it should be cheap; a name
 * field is not. So the name is required and self-reported, asked **at
 * submit** and never as a gate before someone can start typing — and
 * remembered here so working through several rows costs one typing.
 *
 * The server ignores all of this for a signed-in caller: logged in ⇒
 * never anonymous (`apps/opps/public_input.resolve_reviewer`).
 */

const NAME_KEY = "ace.summary.reviewerName";
const EMAIL_KEY = "ace.summary.reviewerEmail";

function read(key: string): string {
  try {
    return window.localStorage.getItem(key) ?? "";
  } catch {
    return "";
  }
}

function write(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* private browsing — the form still works, it just won't prefill */
  }
}

export interface ReviewerIdentity {
  name: string;
  email: string;
}

export function rememberedIdentity(): ReviewerIdentity {
  return { name: read(NAME_KEY), email: read(EMAIL_KEY) };
}

export function rememberIdentity({ name, email }: ReviewerIdentity): void {
  write(NAME_KEY, name.trim());
  write(EMAIL_KEY, email.trim());
}

/** Minimum the server will accept — mirrors `public_input.MIN_NAME_CHARS`. */
export const MIN_NAME_CHARS = 2;
