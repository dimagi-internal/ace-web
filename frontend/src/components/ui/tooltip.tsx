import * as React from "react";
import { Tooltip as TooltipPrimitive } from "@base-ui/react/tooltip";

import { cn } from "@/lib/utils";

/**
 * Thin wrapper around @base-ui/react's Tooltip primitive that matches
 * the rest of the shadcn-ish ui/ collection. Use <Tooltip> for any
 * icon-only button so sighted users get hover feedback that mirrors
 * the aria-label exposed to AT.
 *
 * Usage:
 *   <Tooltip label="Delete this opp">
 *     <button aria-label="Delete foo">...</button>
 *   </Tooltip>
 *
 * The child is rendered via base-ui's `render` prop so the existing
 * button element (with its aria-label, classes, handlers) is preserved.
 */
const TooltipProvider = TooltipPrimitive.Provider;

interface TooltipProps {
  /** Tooltip text. Should mirror the trigger's aria-label. */
  label: React.ReactNode;
  /** The interactive element to attach the tooltip to. */
  children: React.ReactElement;
  /** Open delay in ms. */
  delay?: number;
  /** Side of the trigger to place the popup. */
  side?: "top" | "right" | "bottom" | "left";
  /** Offset (px) from the trigger. */
  sideOffset?: number;
}

function Tooltip({ label, children, delay = 300, side = "top", sideOffset = 6 }: TooltipProps) {
  return (
    <TooltipPrimitive.Root>
      <TooltipPrimitive.Trigger delay={delay} render={children} />
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Positioner side={side} sideOffset={sideOffset}>
          <TooltipPrimitive.Popup
            className={cn(
              "z-50 max-w-xs rounded-md border border-border bg-popover px-2 py-1 text-xs text-popover-foreground shadow-md",
              "data-[ending-style]:opacity-0 data-[starting-style]:opacity-0 transition-opacity",
            )}
          >
            {label}
          </TooltipPrimitive.Popup>
        </TooltipPrimitive.Positioner>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  );
}

export { Tooltip, TooltipProvider };
