package scanner

import (
	"os"
	"path/filepath"
	"strings"
)

func (s *Scanner) wwnFallback(deviceName string) string {
	wwidPath := filepath.Join("/sys/class/block", deviceName, "device", "wwid")
	data, err := os.ReadFile(wwidPath)
	if err != nil {
		return s.wwnFromUdev(deviceName)
	}
	wwn := strings.TrimSpace(string(data))
	if strings.HasPrefix(wwn, "naa.") {
		wwn = strings.TrimPrefix(wwn, "naa.")
	}
	if wwn != "" {
		return strings.ToLower(wwn)
	}
	return s.wwnFromUdev(deviceName)
}

func (s *Scanner) wwnFromUdev(deviceName string) string {
	devNo, err := os.ReadFile(filepath.Join("/sys/class/block", deviceName, "dev"))
	if err != nil {
		return ""
	}

	udevID := "b" + strings.TrimSpace(string(devNo))
	udevBytes, err := os.ReadFile(filepath.Join("/run/udev/data/", udevID))
	if err != nil {
		return ""
	}

	for _, line := range strings.Split(string(udevBytes), "\n") {
		if strings.HasPrefix(line, "E:ID_WWN=") {
			return strings.ToLower(strings.TrimPrefix(line, "E:ID_WWN="))
		}
	}

	return ""
}
