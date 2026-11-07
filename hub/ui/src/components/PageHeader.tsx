import type { ReactNode } from "react";

interface PageHeaderProps {
  title: string;
  description?: string;
  children?: ReactNode;
}

export function PageHeader({ title, description, children }: PageHeaderProps) {
  return (
    <div className="relative pt-7 pb-5 sm:pt-9 sm:pb-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0">
          <div className="mb-3 flex items-center gap-2" aria-hidden>
            <span className="from-primary h-px w-9 bg-gradient-to-r via-primary/50 to-transparent" />
            <span className="bg-primary/80 size-1 rounded-full shadow-[0_0_8px_var(--primary)]" />
          </div>
          <h1 className="text-gradient font-display text-[30px] leading-none font-semibold tracking-[-0.04em] sm:text-[36px]">
            {title}
          </h1>
          {description ? (
            <p className="text-muted-foreground mt-2.5 max-w-2xl text-[13px] leading-relaxed">{description}</p>
          ) : null}
        </div>
        {children ? <div className="flex flex-wrap items-center justify-end gap-2">{children}</div> : null}
      </div>
    </div>
  );
}
