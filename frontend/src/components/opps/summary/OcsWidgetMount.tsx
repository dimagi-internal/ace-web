import { useEffect } from "react";

interface Props {
  publicId: string;
  embedKey: string;
  /** OCS host serving widget.js, e.g. "https://chatbots.dimagi.com". */
  host?: string;
}

declare module "react" {
  namespace JSX {
    interface IntrinsicElements {
      "open-chat-studio-widget": {
        "public-id"?: string;
        "embed-key"?: string;
      } & React.HTMLAttributes<HTMLElement>;
    }
  }
}

const SCRIPT_ATTR = "data-ocs-widget";

/**
 * Mounts the standard OCS chatbot widget as a corner-bubble popup.
 * Loads widget.js from `host` once per page (idempotent) and renders the
 * `<open-chat-studio-widget>` web component bound to the bot's
 * public_id + embed_key. Failure to load the script silently no-ops —
 * the page's body-side "Open in OCS" link still works.
 */
export function OcsWidgetMount({
  publicId,
  embedKey,
  host = "https://chatbots.dimagi.com",
}: Props) {
  useEffect(() => {
    if (typeof document === "undefined") return;
    if (document.querySelector(`script[${SCRIPT_ATTR}]`)) return;

    const script = document.createElement("script");
    script.src = `${host.replace(/\/$/, "")}/static/widget.js`;
    script.async = true;
    script.setAttribute(SCRIPT_ATTR, "1");
    script.onerror = () => {
      // Non-fatal — the body link to OCS is the fallback.
      script.remove();
    };
    document.head.appendChild(script);
  }, [host]);

  return (
    <open-chat-studio-widget
      public-id={publicId}
      embed-key={embedKey}
    />
  );
}
