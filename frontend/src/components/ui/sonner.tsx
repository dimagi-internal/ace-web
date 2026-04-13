import { Toaster as SonnerToaster } from "sonner"

import { cn } from "@/lib/utils"

type ToasterProps = React.ComponentProps<typeof SonnerToaster>

export function Toaster({ className, ...props }: ToasterProps) {
  return (
    <SonnerToaster
      className={cn(className)}
      toastOptions={{
        classNames: {
          toast:
            "group toast bg-card text-card-foreground border-border shadow-lg",
          description: "text-muted-foreground",
          actionButton: "bg-primary text-primary-foreground",
          cancelButton: "bg-muted text-muted-foreground",
        },
      }}
      {...props}
    />
  )
}
