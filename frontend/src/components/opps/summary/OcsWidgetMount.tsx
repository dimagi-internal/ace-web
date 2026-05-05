// Side-effect import: registers the <open-chat-studio-widget> custom
// element via Stencil's lazy bootstrap. Must run at module load (not
// inside useEffect) so the element is upgradeable before React inserts
// it — otherwise the first render attaches an unknown tag and the
// widget's internal lookup fails ("Constructor for ... was not found").
import "open-chat-studio-widget";

interface Props {
  /** OCS chatbot's public_id (the "chatbot_public_id" field). */
  chatbotId: string;
  /** OCS embed key (the "chatbot_embed_key" field). */
  embedKey: string;
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

/**
 * Mounts the standard OCS chatbot as a corner-bubble popup.
 *
 * The widget is the npm-distributed ``open-chat-studio-widget`` Stencil
 * component (same package CommCare Connect uses in its base template).
 * The top-of-file ``import`` self-registers the custom element on
 * module load.
 */
export function OcsWidgetMount({ chatbotId, embedKey }: Props) {
  // The widget element itself has no intrinsic size or positioning —
  // Connect wraps it in a `position: fixed` container in their base
  // template (commcare_connect tailwind.css `.chat-widget-container`).
  // We replicate that here so the launcher button shows in the corner.
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
