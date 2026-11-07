import * as React from "react";

import { cn } from "@/lib/utils";

function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn(
        "file:text-foreground placeholder:text-muted-foreground/75 selection:bg-primary selection:text-primary-foreground border-border/75 bg-card/40 flex h-10 w-full min-w-0 rounded-lg border px-3 py-1 text-sm shadow-[inset_0_1px_0_0_oklch(1_0_0/0.035)] transition-[border-color,background-color,box-shadow] outline-none file:inline-flex file:h-7 file:border-0 file:bg-transparent file:text-sm file:font-medium disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50",
        "hover:border-border focus-visible:border-primary/50 focus-visible:bg-card/60 focus-visible:ring-[3px] focus-visible:ring-primary/15",
        "aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/30 aria-invalid:border-destructive",
        className,
      )}
      {...props}
    />
  );
}

export { Input };
