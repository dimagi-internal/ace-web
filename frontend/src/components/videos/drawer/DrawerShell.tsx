import { type ReactNode, useEffect } from "react";

interface Props {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  footerActions: ReactNode;
}

export function DrawerShell({ open, title, onClose, children, footerActions }: Props) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <>
      <div
        className="fixed inset-0 z-40 bg-black/30"
        onClick={onClose}
        aria-hidden
      />
      <aside
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="fixed right-0 top-0 bottom-0 z-50 flex w-[480px] max-w-[90vw] flex-col bg-background shadow-xl"
      >
        <header className="border-b p-4">
          <h2 className="text-base font-semibold">{title}</h2>
        </header>
        <div className="flex-1 overflow-auto p-4">{children}</div>
        <footer className="flex items-center justify-end gap-2 border-t p-4">{footerActions}</footer>
      </aside>
    </>
  );
}
