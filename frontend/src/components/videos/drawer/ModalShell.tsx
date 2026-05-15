import { type ReactNode, useEffect } from "react";

interface Props {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  footerActions: ReactNode;
}

export function ModalShell({ open, title, onClose, children, footerActions }: Props) {
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
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="w-full max-w-2xl rounded-lg bg-background shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="border-b p-4">
          <h2 className="text-base font-semibold">{title}</h2>
        </header>
        <div className="max-h-[70vh] overflow-auto p-4">{children}</div>
        <footer className="flex items-center justify-end gap-2 border-t p-4">{footerActions}</footer>
      </div>
    </div>
  );
}
