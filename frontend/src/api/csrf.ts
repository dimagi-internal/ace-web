/**
 * Read the CSRF token from the browser's cookies. Django's CsrfViewMiddleware
 * (and DRF's SessionAuthentication) require unsafe-method requests to carry
 * this as the X-CSRFToken header.
 *
 * ace-web's prod deployment uses a tenant-specific cookie name
 * (`csrftoken_ace`, set in connectlabs.py) to avoid colliding with other
 * tenants on labs.connect.dimagi.com. Local dev uses the Django default
 * (`csrftoken`). Check the tenant-specific name first, fall back to the
 * default, return empty string if neither is present (an empty header is
 * harmless for safe methods).
 */
export function getCsrfToken(): string {
  const cookies = document.cookie.split(";");
  for (const raw of cookies) {
    const [rawName, ...rawValue] = raw.trim().split("=");
    if (rawName === "csrftoken_ace" || rawName === "csrftoken") {
      return decodeURIComponent(rawValue.join("="));
    }
  }
  return "";
}
