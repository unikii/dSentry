package scanner

import "testing"

func TestFallbackDeviceIdentityIncludesHostname(t *testing.T) {
	a := fallbackDeviceIdentity("host-a", "/dev/sda")
	b := fallbackDeviceIdentity("host-b", "/dev/sda")
	if a == b {
		t.Fatalf("fallback identity must differ across hosts, got %q", a)
	}
	if a != "host-a:/dev/sda" {
		t.Fatalf("unexpected fallback identity: %q", a)
	}
	if got := fallbackDeviceIdentity("", "/dev/sda"); got != "/dev/sda" {
		t.Fatalf("empty hostname should fall back to the device path, got %q", got)
	}
}
