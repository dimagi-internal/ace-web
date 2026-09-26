import {
  Bot,
  FileText,
  Handshake,
  LayoutDashboard,
  Link2,
  Megaphone,
  Network,
  Presentation,
  Sheet,
  Smartphone,
  type LucideIcon,
} from "lucide-react";

import type { RunProductKind } from "@/api/types.ws";

export interface KindMeta {
  readonly icon: LucideIcon;
  /** What to call one before it is built — the replay shows this, not the
   *  real title, until the beat that made it. */
  readonly label: string;
  /** One line for someone who has never seen one. */
  readonly blurb: string;
  /** Label for the button that opens the live thing. */
  readonly openLabel: string;
}

export const KIND_META: Record<RunProductKind, KindMeta> = {
  document: {
    icon: FileText,
    label: "Document",
    blurb: "A document ACE wrote and saved to the run's Drive folder.",
    openLabel: "Open in Drive",
  },
  deck: {
    icon: Presentation,
    label: "Slide deck",
    blurb: "A slide deck ACE built in Google Slides.",
    openLabel: "Open in Slides",
  },
  sheet: {
    icon: Sheet,
    label: "Spreadsheet",
    blurb: "A spreadsheet ACE built in Google Sheets.",
    openLabel: "Open in Sheets",
  },
  commcare_app: {
    icon: Smartphone,
    label: "CommCare app",
    blurb:
      "A real CommCare app, built by Nova from the PDD and released on CommCare HQ. Frontline workers install it on their phones.",
    openLabel: "Open in CommCare HQ",
  },
  connect_opportunity: {
    icon: Handshake,
    label: "Connect opportunity",
    blurb:
      "The live program on CommCare Connect that frontline workers join: its apps, payment units and verification rules.",
    openLabel: "Open in Connect",
  },
  connect_program: {
    icon: Network,
    label: "Connect program",
    blurb: "The Connect program that groups this opportunity with others like it.",
    openLabel: "Open in Connect",
  },
  chatbot: {
    icon: Bot,
    label: "Support chatbot",
    blurb:
      "A support assistant on Open Chat Studio (OCS), answering from the program's own documents, for workers and the LLO.",
    openLabel: "Open in OCS",
  },
  dashboard: {
    icon: LayoutDashboard,
    label: "Dashboard",
    blurb:
      "A live dashboard on Connect Labs, running on generated demo data rather than real program activity.",
    openLabel: "Open dashboard",
  },
  solicitation: {
    icon: Megaphone,
    label: "Solicitation",
    blurb: "The public call for partner organizations to apply to run this program.",
    openLabel: "Open solicitation",
  },
  link: {
    icon: Link2,
    label: "Link",
    blurb: "Something the run created in another system.",
    openLabel: "Open",
  },
};

export function kindMeta(kind: string): KindMeta {
  return KIND_META[kind as RunProductKind] ?? KIND_META.link;
}
