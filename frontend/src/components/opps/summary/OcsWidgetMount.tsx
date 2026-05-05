import { useEffect } from "react";

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
        position?: "left" | "right";
        visible?: "true" | "false";
      } & React.HTMLAttributes<HTMLElement>;
    }
  }
}

/**
 * Mounts the standard OCS chatbot as a corner-bubble popup.
 *
 * The widget is the npm-distributed ``open-chat-studio-widget`` web component
 * (same package CommCare Connect uses in its base template). Importing it
 * once registers the custom element globally; the JSX tag below mounts it.
 */
export function OcsWidgetMount({ chatbotId, embedKey }: Props) {
  useEffect(() => {
    // Side-effect import: the package self-registers the custom element on
    // first import. Lazy so it only loads when this component is on screen.
    // ts-expect-error: package's `exports` map doesn't expose its .d.ts; the
    // import is for the side effect only (custom-element registration).
    // @ts-expect-error: see comment above
    void import("open-chat-studio-widget");
  }, []);

  return (
    <open-chat-studio-widget
      chatbot-id={chatbotId}
      embed-key={embedKey}
      button-text="Need help?"
      position="right"
    />
  );
}
