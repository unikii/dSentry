import { describe, expect, it } from "vitest";
import {
  formatAxisValue,
  formatMetricValue,
  metricMeta,
  metricUnit,
  sampleTime,
} from "./metrics";

describe("metric metadata", () => {
  it("resolves known metrics from the vendored schema", () => {
    expect(metricMeta("temperature_celsius")?.go_field).toBe("TemperatureCelsius");
    expect(metricUnit("total_bytes_written")).toBe("bytes");
    expect(metricUnit("temperature_celsius")).toBe("°C");
  });

  it("returns undefined for unknown metrics", () => {
    expect(metricMeta("no_such_metric")).toBeUndefined();
    expect(metricUnit("no_such_metric")).toBe("");
  });
});

describe("formatMetricValue", () => {
  it("formats by unit", () => {
    expect(formatMetricValue("temperature_celsius", 33.44)).toBe("33.4 °C");
    expect(formatMetricValue("wear_level_pct", 97)).toBe("97%");
    expect(formatMetricValue("total_bytes_written", 1024)).toBe("1 KiB");
    expect(formatMetricValue("power_on_hours", 1234.6)).toBe("1,235 h");
  });

  it("renders bitmasks as hex", () => {
    expect(formatMetricValue("nvme_critical_warning", 0x0b)).toBe("0x0B");
  });

  it("em-dashes missing values", () => {
    expect(formatMetricValue("temperature_celsius", null)).toBe("—");
    expect(formatMetricValue("temperature_celsius", undefined)).toBe("—");
  });
});

describe("formatAxisValue", () => {
  it("compacts large numbers", () => {
    expect(formatAxisValue("total_bytes_written", 2 * 1024 ** 3)).toBe("2 GiB");
    expect(formatAxisValue("power_on_hours", 1234.6)).toBe("1235h");
    expect(formatAxisValue("power_cycles", 1_234_567)).toBe("1.2M");
  });
});

describe("sampleTime", () => {
  it("parses API timestamps as UTC even without a tz suffix", () => {
    expect(sampleTime({ time: "2026-01-15T10:30:00Z" })).toBe(
      Date.parse("2026-01-15T10:30:00.000Z"),
    );
    expect(sampleTime({ time: "2026-01-15 10:30:00" })).toBe(
      Date.parse("2026-01-15T10:30:00.000Z"),
    );
    expect(sampleTime({ time: "bogus" })).toBe(0);
  });
});
