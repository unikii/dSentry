import { AlertTriangle } from "lucide-react";
import type { DeviceResponse } from "@/client";
import { Badge } from "@/components/ui/badge";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useLanguage } from "@/context/use-lang";
import { SMART_STATE_META, smartState, thresholdMeta } from "@/lib/constants";
import { cn } from "@/lib/utils";

interface SmartBadgeProps {
  device: Pick<DeviceResponse, "smart_status" | "smart_enabled" | "smart_available" | "threshold_status" | "last_event_at">;
  showEvent?: boolean;
}

export function SmartBadge({ device, showEvent = true }: SmartBadgeProps) {
  const { t } = useLanguage();
  const state = smartState(device);
  const meta = SMART_STATE_META[state];
  const threshold = thresholdMeta(device.threshold_status);
  const hasEvent = showEvent && !!device.last_event_at;

  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      <Tooltip>
        <TooltipTrigger asChild>
          <Badge variant="outline" className={cn("cursor-help gap-1.5", meta.className)}>
            <span className={cn("size-1.5 shrink-0 rounded-full bg-current", state === "passed" && "status-dot")} />
            {t(meta.labelKey)}
            {hasEvent && <AlertTriangle className="ml-0.5 size-3" />}
          </Badge>
        </TooltipTrigger>
        <TooltipContent>{hasEvent ? t("smart.eventRecorded") : t(meta.tipKey)}</TooltipContent>
      </Tooltip>
      {threshold && (
        <Tooltip>
          <TooltipTrigger asChild>
            <Badge variant="outline" className={cn("cursor-help gap-1.5", threshold.className)}>
              <span className="size-1.5 shrink-0 rounded-full bg-current" />
              {t(threshold.labelKey)}
            </Badge>
          </TooltipTrigger>
          <TooltipContent>{t(threshold.tipKey)}</TooltipContent>
        </Tooltip>
      )}
    </span>
  );
}
