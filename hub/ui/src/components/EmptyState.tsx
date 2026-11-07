import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

interface EmptyStateProps {
  icon: LucideIcon;
  title: string;
  description?: string;
  action?: ReactNode;
}

export function EmptyState({ icon: Icon, title, description, action }: EmptyStateProps) {
  return (
    <div className="panel relative overflow-hidden px-6 py-16 text-center sm:py-20">
      <div className="bg-grid-dense pointer-events-none absolute inset-0 opacity-40 [mask-image:radial-gradient(ellipse_60%_70%_at_50%_45%,black,transparent_75%)]" aria-hidden />
      <div className="from-primary/18 to-primary/0 pointer-events-none absolute top-0 left-1/2 size-48 -translate-x-1/2 -translate-y-1/2 rounded-full bg-gradient-to-b blur-3xl" aria-hidden />
      <div className="relative mx-auto mb-5 flex size-14 items-center justify-center rounded-2xl border border-primary/20 bg-primary/[0.08] text-primary shadow-[inset_0_1px_0_0_oklch(1_0_0/0.08),0_18px_40px_-24px_var(--primary)]">
        <Icon className="size-6" strokeWidth={1.6} />
        <span className="bg-primary absolute -top-1 -right-1 size-1.5 rounded-full" />
      </div>
      <div className="relative">
        <p className="font-display text-base font-semibold tracking-tight">{title}</p>
        {description ? (
          <p className="text-muted-foreground mx-auto mt-2 max-w-md text-[13px] leading-relaxed">{description}</p>
        ) : null}
      </div>
      {action ? <div className="relative mt-5 flex justify-center">{action}</div> : null}
    </div>
  );
}
