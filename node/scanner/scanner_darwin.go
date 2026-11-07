//go:build darwin

package scanner

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"

	"github.com/unikii/dsentry/node/logutil"
)

func DevicePrefix() string {
	return "/dev/"
}

func (s *Scanner) wwnFallback(deviceName string) string {
	return ""
}

func (s *Scanner) resolveDarwinIOServiceDevices(parent context.Context, devices []ScannedDevice) []ScannedDevice {
	needsFix := false
	for _, d := range devices {
		if strings.HasPrefix(d.DeviceName, "IOService:") {
			needsFix = true
			break
		}
	}
	if !needsFix {
		return devices
	}

	fallback, err := s.enumerateDarwinDisks(parent)
	if err != nil || len(fallback) == 0 {
		logutil.Debugf("Warning: failed to enumerate macOS disks, keeping scan results: %v", err)
		return devices
	}
	return fallback
}

var reWholeDisk = regexp.MustCompile(`^disk\d+$`)

func (s *Scanner) enumerateDarwinDisks(parent context.Context) ([]ScannedDevice, error) {
	matches, err := filepath.Glob("/dev/disk[0-9]*")
	if err != nil {
		return nil, fmt.Errorf("glob /dev/disk*: %w", err)
	}
	if len(matches) == 0 {
		return nil, fmt.Errorf("no /dev/disk* entries found")
	}

	// Query diskutil once for the whole scan instead of spawning it per device.
	physical := physicalDarwinDisks(parent)

	bin := s.Config.Commands.SmartctlBin
	var devices []ScannedDevice

	for _, disk := range matches {
		base := filepath.Base(disk)
		if !reWholeDisk.MatchString(base) {
			continue
		}

		if !physical[base] {
			continue
		}

		ctx, cancel := context.WithTimeout(parent, smartctlTimeout)
		cmd := exec.CommandContext(ctx, bin, "-i", "--json", disk)
		output, err := cmd.Output()
		cancel()
		if parent.Err() != nil {
			return nil, parent.Err()
		}
		if err != nil {
			continue
		}

		var info struct {
			SmartSupport struct {
				Available bool `json:"available"`
			} `json:"smart_support"`
			Device struct {
				Type string `json:"type"`
			} `json:"device"`
		}
		if err := json.Unmarshal(output, &info); err != nil {
			continue
		}
		if !info.SmartSupport.Available {
			continue
		}

		deviceType := info.Device.Type
		if deviceType == "" {
			deviceType = "ata"
		}

		devices = append(devices, ScannedDevice{
			DeviceName: base,
			DeviceType: deviceType,
		})
	}

	if len(devices) == 0 {
		return nil, fmt.Errorf("no SMART-capable disks found")
	}

	return devices, nil
}

// physicalDarwinDisks returns the set of whole-disk identifiers (for example
// "disk0") that `diskutil list` reports as physical media. It runs diskutil
// once per scan so enumeration does not spawn a process per device.
func physicalDarwinDisks(parent context.Context) map[string]bool {
	ctx, cancel := context.WithTimeout(parent, smartctlTimeout)
	defer cancel()

	out, err := exec.CommandContext(ctx, "diskutil", "list").Output()
	if err != nil {
		return nil
	}

	physical := make(map[string]bool)
	sc := bufio.NewScanner(strings.NewReader(string(out)))
	for sc.Scan() {
		line := sc.Text()
		if !strings.HasPrefix(line, "/dev/") || !strings.Contains(line, "physical") {
			continue
		}
		// "/dev/disk0 (internal, physical):" -> "disk0"
		id := strings.TrimPrefix(line, "/dev/")
		if i := strings.IndexAny(id, " \t("); i >= 0 {
			id = id[:i]
		}
		if reWholeDisk.MatchString(id) {
			physical[id] = true
		}
	}
	return physical
}
