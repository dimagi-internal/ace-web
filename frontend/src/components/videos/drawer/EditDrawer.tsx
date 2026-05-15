import type { ReactNode } from "react";
import { useBeatEditor } from "../BeatEditorContext";
import { DrawerShell } from "./DrawerShell";
import { ModalShell } from "./ModalShell";
import { ClipTrimPanel } from "./panels/ClipTrimPanel";
import { NarrationPanel } from "./panels/NarrationPanel";
import { StatPanel } from "./panels/StatPanel";

// Default shell. Swap to "modal" if the team prefers it after dogfooding.
const SHELL_MODE: "drawer" | "modal" = "drawer";

export function EditDrawer() {
  const { state, dispatch } = useBeatEditor();
  const target = state.drawerTarget;
  const close = () => dispatch({ type: "CLOSE_DRAWER" });

  if (!target) {
    return null;
  }

  let title: string;
  let body: ReactNode;
  if (target.kind === "clip-trim") {
    title = `Trim ${target.clipKind} #${target.index + 1}`;
    body = (
      <ClipTrimPanel
        clipKind={target.clipKind}
        index={target.index}
        onCommit={close}
        onCancel={close}
      />
    );
  } else if (target.kind === "narration") {
    title = `Voiceover — ${target.beatId}`;
    body = <NarrationPanel beatId={target.beatId} onCommit={close} onCancel={close} />;
  } else {
    title = `Stat — ${target.path}`;
    body = <StatPanel path={target.path} onCommit={close} onCancel={close} />;
  }

  const Shell = SHELL_MODE === "drawer" ? DrawerShell : ModalShell;
  return (
    <Shell open={true} title={title} onClose={close} footerActions={null}>
      {body}
    </Shell>
  );
}
