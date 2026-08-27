import type { ReactNode } from "react";
import { useBeatEditor } from "../BeatEditorContext";
import { sectionLabel } from "../sectionLabels";
import { DrawerShell } from "./DrawerShell";
import { ModalShell } from "./ModalShell";
import { GlobalTemplatePanel } from "./panels/GlobalTemplatePanel";
import { ClipPickerPanel } from "./panels/ClipPickerPanel";
import { ClipTrimPanel } from "./panels/ClipTrimPanel";
import { NarrationPanel } from "./panels/NarrationPanel";
import { ProgramNamePanel } from "./panels/ProgramNamePanel";
import { StatPanel } from "./panels/StatPanel";
import { AiBuildPanel } from "./panels/AiBuildPanel";
import { CaptionPanel } from "./panels/CaptionPanel";
import { LowerThirdPanel } from "./panels/LowerThirdPanel";
import type { ProgramSpec } from "../types";

// Default shell. Swap to "modal" if the team prefers it after dogfooding.
const SHELL_MODE: "drawer" | "modal" = "drawer";

function clipSlotTitle(spec: ProgramSpec, clipKind: "scene-clip" | "product-beat", index: number): string {
  const total = clipKind === "scene-clip"
    ? (spec.scene?.clips?.length ?? 0)
    : (spec.product?.beats?.length ?? 0);
  const beatId = clipKind === "scene-clip" ? "scene" : "product";
  const section = sectionLabel(beatId).name;
  return total > 1
    ? `${section} — clip ${index + 1} of ${total}`
    : `${section} — clip`;
}

function statTitle(path: string): string {
  if (path === "problem") return `${sectionLabel("problem").name} — Big number`;
  const m = /^impact\[(\d+)\]$/.exec(path);
  if (m) return `${sectionLabel("impact").name} — Big number ${parseInt(m[1], 10) + 1}`;
  return `Stat — ${path}`;
}

export function EditDrawer() {
  const { state, effectiveSpec, dispatch } = useBeatEditor();
  const target = state.drawerTarget;
  const close = () => dispatch({ type: "CLOSE_DRAWER" });

  if (!target) {
    return null;
  }

  let title: string;
  let body: ReactNode;
  if (target.kind === "clip-trim") {
    title = clipSlotTitle(effectiveSpec, target.clipKind, target.index);
    body = (
      <ClipTrimPanel
        clipKind={target.clipKind}
        index={target.index}
        onCommit={close}
        onCancel={close}
      />
    );
  } else if (target.kind === "clip-picker") {
    title = `Swap clip — ${clipSlotTitle(effectiveSpec, target.clipKind, target.index)}`;
    body = (
      <ClipPickerPanel
        clipKind={target.clipKind}
        index={target.index}
        onCommit={close}
        onCancel={close}
      />
    );
  } else if (target.kind === "narration") {
    title = `Voiceover — ${sectionLabel(target.beatId).name}`;
    body = <NarrationPanel beatId={target.beatId} onCommit={close} onCancel={close} />;
  } else if (target.kind === "global-template") {
    title = `On screen — ${sectionLabel(target.beatId).name}`;
    body = <GlobalTemplatePanel beatId={target.beatId} onCommit={close} onCancel={close} />;
  } else if (target.kind === "program-name") {
    title = "Rename program";
    body = <ProgramNamePanel onCommit={close} onCancel={close} />;
  } else if (target.kind === "stat") {
    title = statTitle(target.path);
    body = <StatPanel path={target.path} onCommit={close} onCancel={close} />;
  } else if (target.kind === "ai-build") {
    title = `Card — ${sectionLabel(target.beatId).name}`;
    body = <AiBuildPanel onCommit={close} onCancel={close} />;
  } else if (target.kind === "caption") {
    title = `${sectionLabel("product").name} — caption ${target.index + 1}`;
    body = <CaptionPanel index={target.index} onCommit={close} onCancel={close} />;
  } else {
    // lower-third
    title = `${sectionLabel("scene").name} — lower third`;
    body = <LowerThirdPanel onCommit={close} onCancel={close} />;
  }

  const Shell = SHELL_MODE === "drawer" ? DrawerShell : ModalShell;
  return (
    <Shell open={true} title={title} onClose={close} footerActions={null}>
      {body}
    </Shell>
  );
}
