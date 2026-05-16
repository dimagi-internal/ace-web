import { createContext, useContext } from "react";

// Phase → Agent/Skill is the default mental model. Tools below that level
// are rarely useful when you're scanning for "where did the money go" — they
// hide by default and the user opts in via the toggle in StructureTab.
interface StructureViewOptions {
  showTools: boolean;
}

export const StructureViewContext = createContext<StructureViewOptions>({
  showTools: false,
});

export function useStructureView(): StructureViewOptions {
  return useContext(StructureViewContext);
}
