import type { DeviceResponse } from "@/client";
import type { MessageKey } from "@/context/lang-context";

/* ------------------------------------------------------------------ */
/* Device types                                                        */
/* ------------------------------------------------------------------ */

export interface DeviceTypeMeta {
  label: string;
  /** tailwind classes for the accent badge */
  badge: string;
  /** tailwind gradient stops for the card top accent bar */
  bar: string;
  /** tailwind classes for the card glyph tile */
  icon: string;
  media: "SSD" | "HDD" | "NVMe";
}

export const DEVICE_TYPE_META: Record<string, DeviceTypeMeta> = {
  nvme: {
    label: "NVMe",
    badge: "border-nvme/25 bg-nvme/10 text-nvme",
    bar: "from-nvme/80 via-nvme/25 to-transparent",
    icon: "border-nvme/20 bg-nvme/[0.08] text-nvme",
    media: "NVMe",
  },
  ata_ssd: {
    label: "SATA SSD",
    badge: "border-ata-ssd/25 bg-ata-ssd/10 text-ata-ssd",
    bar: "from-ata-ssd/80 via-ata-ssd/25 to-transparent",
    icon: "border-ata-ssd/20 bg-ata-ssd/[0.08] text-ata-ssd",
    media: "SSD",
  },
  ata_hdd: {
    label: "SATA HDD",
    badge: "border-ata-hdd/25 bg-ata-hdd/10 text-ata-hdd",
    bar: "from-ata-hdd/80 via-ata-hdd/25 to-transparent",
    icon: "border-ata-hdd/20 bg-ata-hdd/[0.08] text-ata-hdd",
    media: "HDD",
  },
  scsi_ssd: {
    label: "SCSI SSD",
    badge: "border-scsi-ssd/25 bg-scsi-ssd/10 text-scsi-ssd",
    bar: "from-scsi-ssd/80 via-scsi-ssd/25 to-transparent",
    icon: "border-scsi-ssd/20 bg-scsi-ssd/[0.08] text-scsi-ssd",
    media: "SSD",
  },
  scsi_hdd: {
    label: "SCSI HDD",
    badge: "border-scsi-hdd/25 bg-scsi-hdd/10 text-scsi-hdd",
    bar: "from-scsi-hdd/80 via-scsi-hdd/25 to-transparent",
    icon: "border-scsi-hdd/20 bg-scsi-hdd/[0.08] text-scsi-hdd",
    media: "HDD",
  },
};

export function deviceTypeMeta(type?: string | null): DeviceTypeMeta {
  return DEVICE_TYPE_META[type ?? ""] ?? {
    label: (type ?? "unknown").toUpperCase(),
    badge: "border-border/70 bg-secondary/70 text-muted-foreground",
    bar: "from-muted-foreground/60 via-muted-foreground/20 to-transparent",
    icon: "border-border/70 bg-secondary/70 text-muted-foreground",
    media: "SSD",
  };
}

/* ------------------------------------------------------------------ */
/* SMART status                                                        */
/* ------------------------------------------------------------------ */

export type SmartState = "passed" | "failed" | "na";

export function smartState(d: Pick<DeviceResponse, "smart_status" | "smart_enabled" | "smart_available">): SmartState {
  if (d.smart_status === 1) return "failed";
  if (d.smart_status === 0 && d.smart_enabled) return "passed";
  return "na";
}

export const SMART_STATE_META: Record<SmartState, { labelKey: MessageKey; className: string; tipKey: MessageKey }> = {
  passed: {
    labelKey: "smart.passed",
    className: "border-success/25 bg-success/10 text-success",
    tipKey: "smart.tipPassed",
  },
  failed: {
    labelKey: "smart.failed",
    className: "border-destructive/30 bg-destructive/10 text-destructive",
    tipKey: "smart.tipFailed",
  },
  na: {
    labelKey: "smart.na",
    className: "border-border/70 bg-secondary/70 text-muted-foreground",
    tipKey: "smart.tipNA",
  },
};

export function thresholdMeta(
  status?: number | null,
): { labelKey: MessageKey; tipKey: MessageKey; className: string } | null {
  if (status === 1) {
    return {
      labelKey: "smart.warning",
      tipKey: "smart.tipThresholdWarning",
      className: "border-warning/30 bg-warning/10 text-warning",
    };
  }
  if (status === 2) {
    return {
      labelKey: "smart.critical",
      tipKey: "smart.tipThresholdCritical",
      className: "border-destructive/30 bg-destructive/10 text-destructive",
    };
  }
  return null;
}

/* ------------------------------------------------------------------ */
/* Device status LED                                                   */
/* ------------------------------------------------------------------ */

export type DeviceLedColor = "green" | "amber" | "red" | "cyan" | "violet";

const DEVICE_LED_COLOR: Record<string, DeviceLedColor> = {
  passed: "green",
  failed: "red",
  warning: "amber",
  critical: "red",
  na: "cyan",
  unknown: "cyan",
  archived: "violet",
  // Device types (for type-tinted LEDs).
  nvme: "violet",
  ata_ssd: "cyan",
  ata_hdd: "amber",
  scsi_ssd: "green",
  scsi_hdd: "red",
  "0": "green",
  "1": "red",
  "2": "amber",
};

type DeviceLedInput =
  | string
  | number
  | (Pick<DeviceResponse, "smart_status" | "smart_enabled" | "smart_available"> & {
      threshold_status?: number | null;
      archived?: boolean;
    })
  | null
  | undefined;

function resolveDeviceLedColor(input: DeviceLedInput): DeviceLedColor {
  if (input === null || input === undefined) return DEVICE_LED_COLOR.na;
  if (typeof input === "string" || typeof input === "number") {
    return DEVICE_LED_COLOR[String(input)] ?? DEVICE_LED_COLOR.na;
  }
  if (input.archived) return DEVICE_LED_COLOR.archived;
  if (input.threshold_status === 2) return DEVICE_LED_COLOR.critical;
  if (input.threshold_status === 1) return DEVICE_LED_COLOR.warning;
  if (input.smart_status === 1) return DEVICE_LED_COLOR.failed;
  if (input.smart_status === 0 && input.smart_enabled) return DEVICE_LED_COLOR.passed;
  return DEVICE_LED_COLOR.na;
}

/**
 * LED colour for a device, using the shared status palette.
 *
 * Accepts a device (or a SMART state / status code / device type); the
 * per-state colours are also exposed as properties for legends.
 */
export const deviceLedColor = Object.assign(resolveDeviceLedColor, DEVICE_LED_COLOR);

/* ------------------------------------------------------------------ */
/* Events                                                              */
/* ------------------------------------------------------------------ */

export const EVENT_TYPE_META: Record<string, { labelKey: MessageKey; className: string }> = {
  device_smart_fail: {
    labelKey: "event.smartFail",
    className: "border-destructive/30 bg-destructive/10 text-destructive",
  },
  device_smart_success: {
    labelKey: "event.smartRecovery",
    className: "border-success/25 bg-success/10 text-success",
  },
  device_threshold_warning: {
    labelKey: "event.thresholdWarning",
    className: "border-warning/30 bg-warning/10 text-warning",
  },
  device_threshold_critical: {
    labelKey: "event.thresholdCritical",
    className: "border-destructive/30 bg-destructive/10 text-destructive",
  },
  device_missing: {
    labelKey: "event.deviceMissing",
    className: "border-warning/30 bg-warning/10 text-warning",
  },
  device_online: {
    labelKey: "event.deviceOnline",
    className: "border-success/25 bg-success/10 text-success",
  },
};

export function eventTypeMeta(type: string): { labelKey: MessageKey | null; className: string } {
  return (
    EVENT_TYPE_META[type] ?? { labelKey: null, className: "border-border/70 bg-secondary/70 text-muted-foreground" }
  );
}

/** Resolve an event-type label, falling back to the raw type string when unknown. */
export function eventTypeLabel(type: string, t: (key: MessageKey) => string): string {
  const meta = eventTypeMeta(type);
  return meta.labelKey ? t(meta.labelKey) : type;
}

/* ------------------------------------------------------------------ */
/* Alert types (mirror of services/alerts.py VALID_ALERT_TYPES) */
/* ------------------------------------------------------------------ */

export interface AlertTypeMeta {
  label: string;
  placeholder: string;
  hintKey?: MessageKey;
}

export const ALERT_TYPES: Record<string, AlertTypeMeta> = {
  email: { label: "Email", placeholder: "you@example.com", hintKey: "alerts.hintEmail" },
  discord: { label: "Discord", placeholder: "discord://webhook_id/webhook_token" },
  telegram: { label: "Telegram", placeholder: "tgram://bot_token/chat_id" },
  slack: { label: "Slack", placeholder: "slack://tokenA/tokenB/tokenC/#channel" },
  ntfy: { label: "ntfy", placeholder: "ntfy://topic" },
  gotify: { label: "Gotify", placeholder: "gotify://hostname/token" },
  pushover: { label: "Pushover", placeholder: "pover://user@token" },
  pushbullet: { label: "Pushbullet", placeholder: "pbul://accesstoken" },
  generic_webhook: {
    label: "Generic Webhook",
    placeholder: "json://example.com/hook",
    hintKey: "alerts.hintGenericWebhook",
  },
  google_chat: { label: "Google Chat", placeholder: "gchat://workspace/key/token" },
  matrix: { label: "Matrix", placeholder: "matrix://user:pass@hostname/#room" },
  mattermost: { label: "Mattermost", placeholder: "mmost://hostname/token" },
  msteams: { label: "MS Teams (Workflow)", placeholder: "workflow://host/workflow/signature" },
  wechat_work: { label: "WeChat Work", placeholder: "wechat://corpid:corpsecret@agentid" },
  dingtalk: { label: "DingTalk", placeholder: "dingtalk://token/..." },
  feishu: { label: "Feishu", placeholder: "feishu://token" },
  prowl: { label: "Prowl", placeholder: "prowl://apikey" },
  ifttt: { label: "IFTTT", placeholder: "ifttt://webhook_key/event" },
  linenotify: { label: "LINE Notify", placeholder: "line://token" },
};

export const ALERT_TYPE_KEYS = Object.keys(ALERT_TYPES);

export const MAX_ENABLED_ALERTS = 2;

/* ------------------------------------------------------------------ */
/* Misc                                                                */
/* ------------------------------------------------------------------ */

export const PAGE_SIZE_OPTIONS = [10, 20, 50, 100];
