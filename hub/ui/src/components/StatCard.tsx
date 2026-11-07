import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

type StatTone = "primary" | "success" | "warning" | "danger" | "info" | "neutral";

const TONES: Record<StatTone, string> = {
  primary: "border-primary/20 bg-primary/10 text-primary",
  success: "border-success/20 bg-success/10 text-success",
  warning: "border-warning/25 bg-warning/10 text-warning",
  danger: "border-destructive/25 bg-destructive/10 text-destructive",
  info: "border-info/25 bg-info/10 text-info",
  neutral: "border-border/65 bg-secondary/60 text-muted-foreground",
};

interface StatCardProps {
  icon: LucideIcon;
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  tone?: StatTone;
  visual?: ReactNode;
  className?: string;
}

export function StatCard({ icon: Icon, label, value, hint, tone = "primary", visual, className }: StatCardProps) {
  return (
    <div className={cn("group relative flex min-w-0 flex-col gap-3 p-4 sm:p-5", className)}>
      <div className="pointer-events-none absolute inset-0 bg-gradient-to-br from-white/[0.025] to-transparent opacity-0 transition-opacity duration-300 group-hover:opacity-100" />
      <div className="relative flex items-start justify-between gap-3">
        <p className="mono-label text-muted-foreground/85">{label}</p>
        <span className={cn("flex size-8 shrink-0 items-center justify-center rounded-lg border", TONES[tone])}>
          <Icon className="size-4" strokeWidth={1.8} />
        </span>
      </div>
      <div className="relative flex items-end justify-between gap-3">
        <div className="min-w-0">
          <p className="tnum font-display text-[27px] leading-none font-semibold tracking-[-0.03em] sm:text-[31px]">
            {value}
          </p>
          {hint ? <p className="text-muted-foreground mt-2 line-clamp-2 text-[11px] leading-snug">{hint}</p> : null}
        </div>
        {visual}
      </div>
    </div>
  );
}
