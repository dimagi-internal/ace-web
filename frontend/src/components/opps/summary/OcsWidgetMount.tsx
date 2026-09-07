import { useEffect } from "react";

interface Props {
  /** OCS chatbot's public_id (the "chatbot_public_id" field). */
  chatbotId: string;
  /** OCS embed key (the "chatbot_embed_key" field). */
  embedKey: string;
  /** OCS package version to pin against. */
  version?: string;
}

declare module "react" {
  namespace JSX {
    interface IntrinsicElements {
      "open-chat-studio-widget": {
        "chatbot-id"?: string;
        "embed-key"?: string;
        "button-text"?: string;
        position?: "left" | "right" | "center";
        visible?: "true" | "false";
      } & React.HTMLAttributes<HTMLElement>;
    }
  }
}

const SCRIPT_ATTR = "data-ocs-widget";

/**
 * Mounts the OCS chatbot as a corner-bubble popup.
 *
 * Loads the widget from unpkg as an ES module rather than bundling it
 * via Vite. The widget is a Stencil component that lazy-loads its own
 * sub-chunks at runtime relative to its script URL — bundling it
 * inline silently breaks that runtime resolution and the widget
 * upgrades to an empty shadow root. Loading from unpkg keeps the
 * chunks co-located with the entry the way Stencil expects.
 *
 * Same package Connect uses; Connect bundles via Webpack
 * which handles the lazy chunks differently.
 *
 * ## Keep this pin at or above OCS's deprecation floor
 *
 * OCS retires old widget rungs on a published schedule
 * (`apps/channels/widget_versions.py` in dimagi/open-chat-studio):
 *
 *     DEPRECATIONS = [WidgetDeprecation(below_version="0.6.0",
 *                                       sunset_at=datetime(2026, 10, 1, UTC))]
 *
 * This mount was pinned to `0.5.3` — BELOW that floor, sunsetting 2026-10-01.
 * The run-summary page is un-authed and the widget is the one thing on it an
 * outsider can actually use without being granted anything, so it going dark is
 * not cosmetic: the page would keep inviting people to ask questions of a bubble
 * that no longer answers.
 *
 * Pinned to OCS's own `LATEST_VERSION` (0.12.0). The attribute API is unchanged
 * across the bump — OCS's own embed template at HEAD
 * (`templates/experiments/share/widget.html`) hands out exactly these attributes
 * against `widget_script_url()`, which resolves to LATEST_VERSION.
 *
 * When bumping, re-read that file rather than trusting this comment: the floor
 * moves, and a pin that sat still is how this one expired.
 */
export function OcsWidgetMount({ chatbotId, embedKey, version = "0.12.0" }: Props) {
  useEffect(() => {
    if (typeof document === "undefined") return;
    if (document.querySelector(`script[${SCRIPT_ATTR}]`)) return;
    const s = document.createElement("script");
    s.type = "module";
    s.src = `https://unpkg.com/open-chat-studio-widget@${version}/dist/open-chat-studio-widget/open-chat-studio-widget.esm.js`;
    s.async = true;
    s.setAttribute(SCRIPT_ATTR, "1");
    document.head.appendChild(s);
  }, [version]);

  return (
    <div
      style={{
        position: "fixed",
        right: 20,
        bottom: 20,
        zIndex: 100,
      }}
    >
      <open-chat-studio-widget
        chatbot-id={chatbotId}
        embed-key={embedKey}
        button-text="Need help?"
        position="right"
        visible="false"
      />
    </div>
  );
}
