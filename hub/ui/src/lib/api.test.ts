import { describe, expect, it } from "vitest";

import { joinUrl } from "./api";

describe("joinUrl", () => {
  it("joins an origin and a relative base", () => {
    expect(joinUrl("https://ui.example.com", "/api")).toBe("https://ui.example.com/api");
  });

  it("does not duplicate slashes", () => {
    expect(joinUrl("https://ui.example.com/", "/api/")).toBe("https://ui.example.com/api");
  });

  it("uses an absolute API base instead of concatenating it", () => {
    expect(joinUrl("https://ui.example.com", "https://api.example.com")).toBe("https://api.example.com");
  });

  it("keeps a path when either side is empty", () => {
    expect(joinUrl("", "/api")).toBe("/api");
  });
});
