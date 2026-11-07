package scanner

import (
	"strings"
	"testing"

	"github.com/unikii/dsentry/node/config"
)

func scanResult(devices ...ScanDevice) ScanResult {
	return ScanResult{Devices: devices}
}

func deviceTypeSet(devices []ScannedDevice) map[string]string {
	set := make(map[string]string, len(devices))
	for _, d := range devices {
		set[strings.ToLower(d.DeviceName)] = d.DeviceType
	}
	return set
}

func TestGroupScannedDevicesIgnoreOverride(t *testing.T) {
	result := scanResult(
		ScanDevice{Name: "/dev/sda", Type: "sat"},
		ScanDevice{Name: "/dev/sdb", Type: "sat"},
	)
	overrides := []config.DeviceOverride{{Device: "/dev/sdb", Ignore: true}}

	got := groupScannedDevices(result, overrides)
	if len(got) != 1 || got[0].DeviceName != "sda" {
		t.Fatalf("got %+v, want only /dev/sda", got)
	}
}

func TestGroupScannedDevicesTypeOverrideReplacesEntry(t *testing.T) {
	result := scanResult(ScanDevice{Name: "/dev/bus/0", Type: "sat"})
	overrides := []config.DeviceOverride{{
		Device: "/dev/bus/0",
		Type:   []string{"megaraid,14", "megaraid,15"},
	}}

	got := groupScannedDevices(result, overrides)
	if len(got) != 2 {
		t.Fatalf("got %+v, want one entry per RAID type", got)
	}
	types := map[string]bool{}
	for _, d := range got {
		if d.DeviceName != "bus/0" {
			t.Errorf("device name = %q, want bus/0", d.DeviceName)
		}
		types[d.DeviceType] = true
	}
	if !types["megaraid,14"] || !types["megaraid,15"] {
		t.Fatalf("device types = %v, want megaraid,14 and megaraid,15", types)
	}
}

func TestGroupScannedDevicesOverrideAddsMissingDeviceWithDefaultType(t *testing.T) {
	// The scan missed the drive entirely; an override without a type brings
	// it in with the conservative default "ata".
	result := scanResult(ScanDevice{Name: "/dev/sda", Type: "sat"})
	overrides := []config.DeviceOverride{{Device: "/dev/sdz"}}

	got := groupScannedDevices(result, overrides)
	set := deviceTypeSet(got)
	if set["sdz"] != "ata" {
		t.Fatalf("got %+v, want sdz with default type ata", got)
	}
}

func TestGroupScannedDevicesOverrideMatchingIsCaseInsensitive(t *testing.T) {
	result := scanResult(ScanDevice{Name: "/dev/sda", Type: "sat"})
	overrides := []config.DeviceOverride{{Device: "/dev/SDA", Ignore: true}}

	if got := groupScannedDevices(result, overrides); len(got) != 0 {
		t.Fatalf("got %+v, want the uppercase override to match the scanned device", got)
	}
}

func TestGroupScannedDevicesEmptyOverridesKeepsScan(t *testing.T) {
	result := scanResult(
		ScanDevice{Name: "/dev/nvme0", Type: "nvme"},
		ScanDevice{Name: "/dev/sda", Type: "sat"},
	)

	got := groupScannedDevices(result, nil)
	if len(got) != 2 {
		t.Fatalf("got %+v, want both scanned devices", got)
	}
	set := deviceTypeSet(got)
	if set["nvme0"] != "nvme" || set["sda"] != "sat" {
		t.Fatalf("device types = %v, want scanned types preserved", set)
	}
}
