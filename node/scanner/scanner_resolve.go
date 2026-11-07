//go:build !darwin

package scanner

import "context"

func (s *Scanner) resolveDarwinIOServiceDevices(_ context.Context, devices []ScannedDevice) []ScannedDevice {
	return devices
}
