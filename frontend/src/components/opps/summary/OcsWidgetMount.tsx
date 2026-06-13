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
 */
export function OcsWidgetMount({ chatbotId, embedKey, version = "0.5.3" }: Props) {
  useEffect(() => {
    if (typeof document === "undefined") return;
    if (document.querySelector(`script[${SCRIPT_ATTR}]`)) return;
    const s = document.createElement("script");
    s.type = "module";
    s.src = `https://www.unpkg.com/open-chat-studio-widget@${version}/dist/open-chat-studio-widget/open-chat-studio-widget.esm.js`;
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
