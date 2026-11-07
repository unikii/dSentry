import { cn } from "@/lib/utils";

type RingTone = "success" | "warning" | "danger" | "primary";

const TONE_CLASS: Record<RingTone, string> = {
  success: "text-success",
  warning: "text-warning",
  danger: "text-destructive",
  primary: "text-primary",
};

interface HealthRingProps {
  value: number;
  size?: number;
  stroke?: number;
  tone?: RingTone;
  label?: string;
  className?: string;
}

export function HealthRing({ value, size = 56, stroke = 5, tone = "success", label, className }: HealthRingProps) {
  const clamped = Math.max(0, Math.min(100, value));
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (clamped / 100) * circumference;

  return (
    <div
      className={cn("relative shrink-0", TONE_CLASS[tone], className)}
      style={{ width: size, height: size }}
      role="img"
      aria-label={`${Math.round(clamped)}%`}
    >
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="-rotate-90">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="currentColor"
          strokeOpacity={0.14}
          strokeWidth={stroke}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="currentColor"
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          className="transition-[stroke-dashoffset] duration-700 ease-out"
        />
      </svg>
      <span className="absolute inset-0 flex items-center justify-center font-mono text-[10px] font-semibold tracking-tight tabular-nums">
        {label ?? `${Math.round(clamped)}%`}
      </span>
    </div>
  );
}
