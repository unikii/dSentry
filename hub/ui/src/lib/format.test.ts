import { describe, expect, it } from "vitest";
import { formatBytes, formatNumber, formatRelative, formatSiBytes, parseUTC } from "./format";

describe("parseUTC", () => {
  it("treats SQLite 'YYYY-MM-DD HH:MM:SS' as UTC, not local time", () => {
    const d = parseUTC("2026-01-15 10:30:00");
    expect(d?.toISOString()).toBe("2026-01-15T10:30:00.000Z");
  });

  it("parses ISO strings with an explicit offset", () => {
    expect(parseUTC("2026-01-15T10:30:00Z")?.toISOString()).toBe("2026-01-15T10:30:00.000Z");
    expect(parseUTC("2026-01-15T10:30:00+02:00")?.toISOString()).toBe("2026-01-15T08:30:00.000Z");
  });

  it("returns null for missing or garbage input", () => {
    expect(parseUTC(null)).toBeNull();
    expect(parseUTC(undefined)).toBeNull();
    expect(parseUTC("")).toBeNull();
    expect(parseUTC("not a date")).toBeNull();
  });
});

describe("formatBytes", () => {
  it("formats binary units", () => {
    expect(formatBytes(0)).toBe("0 B");
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(1024)).toBe("1 KiB");
    expect(formatBytes(500107862016)).toBe("466 GiB");
    expect(formatBytes(2 * 1024 ** 4)).toBe("2 TiB");
  });

  it("handles negatives and junk", () => {
    expect(formatBytes(-1024)).toBe("-1 KiB");
    expect(formatBytes(null)).toBe("—");
    expect(formatBytes(undefined)).toBe("—");
    expect(formatBytes(Number.NaN)).toBe("—");
  });
});

describe("formatSiBytes", () => {
  it("formats SI (1000-based) units", () => {
    expect(formatSiBytes(1000)).toBe("1 KB");
    expect(formatSiBytes(1_000_000_000)).toBe("1 GB");
    expect(formatSiBytes(2 * 1000 ** 4)).toBe("2 TB");
  });
});

describe("formatRelative", () => {
  it("buckets elapsed time", () => {
    const now = Date.now();
    expect(formatRelative(new Date(now - 30_000).toISOString())).toBe("just now");
    expect(formatRelative(new Date(now - 5 * 60_000).toISOString())).toBe("5m ago");
    expect(formatRelative(new Date(now - 3 * 3_600_000).toISOString())).toBe("3h ago");
    expect(formatRelative(new Date(now - 2 * 86_400_000).toISOString())).toBe("2d ago");
  });

  it("marks future timestamps", () => {
    const now = Date.now();
    expect(formatRelative(new Date(now + 10 * 60_000).toISOString())).toBe("10m from now");
  });

  it("falls back to 'never'", () => {
    expect(formatRelative(null)).toBe("never");
    expect(formatRelative("garbage")).toBe("never");
  });
});

describe("formatNumber", () => {
  it("uses locale grouping and em-dashes for junk", () => {
    expect(formatNumber(1234567)).toBe((1234567).toLocaleString());
    expect(formatNumber(null)).toBe("—");
  });
});
