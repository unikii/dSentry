package scanner

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"os/exec"
	"runtime"
	"strings"
	"time"

	"github.com/unikii/dsentry/node/config"
	"github.com/unikii/dsentry/node/logutil"
	smartctl "github.com/unikii/dsentry/node/smartctl"
)

type Scanner struct {
	Config *config.Config
}

type ScannedDevice struct {
	DeviceName string
	DeviceType string
	RawOutput  []byte
	Meta       *smartctl.DeviceMeta
	MetaHash   string
	DeviceHash string
}

func New(cfg *config.Config) *Scanner {
	return &Scanner{Config: cfg}
}

const smartctlTimeout = 120 * time.Second

type ScanDevice struct {
	Name     string `json:"name"`
	InfoName string `json:"info_name"`
	Type     string `json:"type"`
	Protocol string `json:"protocol"`
}

type ScanResult struct {
	JSONFormatVersion []int        `json:"json_format_version"`
	Devices           []ScanDevice `json:"devices"`
}

func (s *Scanner) RunSmartctlScanContext(parent context.Context) ([]ScannedDevice, error) {
	bin := s.Config.Commands.SmartctlBin
	args, err := splitCommandArgs(s.Config.Commands.MetricsScanArgs)
	if err != nil {
		return nil, fmt.Errorf("parse scan arguments: %w", err)
	}

	ctx, cancel := context.WithTimeout(parent, smartctlTimeout)
	defer cancel()
	cmd := exec.CommandContext(ctx, bin, args...)
	output, err := cmd.Output()
	if err != nil {
		if parent.Err() != nil {
			return nil, parent.Err()
		}
		return nil, fmt.Errorf("smartctl scan failed: %w", err)
	}

	var scanResult ScanResult
	if err := json.Unmarshal(output, &scanResult); err != nil {
		return nil, fmt.Errorf("parsing scan output: %w", err)
	}

	devices := groupScannedDevices(scanResult, s.Config.Devices)

	if runtime.GOOS == "darwin" {
		devices = s.resolveDarwinIOServiceDevices(parent, devices)
	}

	return devices, nil
}

func (s *Scanner) PopulateDeviceInfoContext(parent context.Context, devices []ScannedDevice) ([]ScannedDevice, error) {
	for i := range devices {
		if err := parent.Err(); err != nil {
			return devices, err
		}
		d := &devices[i]

		rawOutput, err := s.RunSmartctlXallContext(parent, d.DeviceName, d.DeviceType)
		if err != nil {
			log.Printf("Warning: skipping %s (%s): smartctl xall failed: %v", d.DeviceName, d.DeviceType, err)
			continue
		}
		d.RawOutput = rawOutput

		var output smartctl.SmartctlOutput
		if err := json.Unmarshal(rawOutput, &output); err != nil {
			log.Printf("Warning: skipping %s: parsing SMART JSON failed: %v", d.DeviceName, err)
			continue
		}
		output.Normalize()

		if output.ModelName == "" && output.SerialNumber == "" {
			log.Printf("Warning: skipping %s: SMART output has no identifying information", d.DeviceName)
			continue
		}

		wwnFallback := s.wwnFallback(d.DeviceName)
		if wwnFallback == "" && (output.SerialNumber == "" || output.SerialNumber == "000000000000") && output.WWN == nil && output.LogicalUnitID == "" {
			// Firmware exposed no serial, WWN, or logical unit identifier.
			// Scope the path fallback to this host so two machines with the
			// same disk layout don't register the same hash as one device.
			wwnFallback = fallbackDeviceIdentity(smartctl.GetHostname(), d.DeviceName)
		}

		protocol, err := smartctl.DetectProtocol(&output)
		if err != nil {
			log.Printf("Warning: skipping %s: SMART protocol detection failed: %v", d.DeviceName, err)
			continue
		}

		parser, err := smartctl.GetParser(protocol)
		if err != nil {
			log.Printf("Warning: skipping %s: no parser for protocol %s: %v", d.DeviceName, protocol, err)
			continue
		}

		meta, err := parser.ParseMeta(&output)
		if err != nil {
			log.Printf("Warning: skipping %s: SMART metadata parse failed: %v", d.DeviceName, err)
			continue
		}

		meta.DeviceName = d.DeviceName

		d.Meta = meta
		d.DeviceHash = smartctl.ComputeDeviceHash(&output, wwnFallback)
		meta.DeviceHash = d.DeviceHash
		d.MetaHash = smartctl.ComputeMetaHash(meta)
		logutil.Debugf("Device metadata: name=%q, protocol=%s, model=%q, serial_present=%v, capacity_bytes=%d, device_hash=%s, meta_hash=%s",
			d.DeviceName, meta.Protocol, meta.ModelName, meta.SerialNumber != "", meta.TotalCapacityBytes, d.DeviceHash, d.MetaHash)
	}
	if err := parent.Err(); err != nil {
		return devices, err
	}

	return devices, nil
}

func (s *Scanner) RunSmartctlXallContext(parent context.Context, deviceName, deviceType string) ([]byte, error) {
	bin := s.Config.Commands.SmartctlBin
	fullName := DevicePrefix() + deviceName
	args, err := s.smartctlArgs(deviceName, deviceType, true)
	if err != nil {
		return nil, err
	}

	ctx, cancel := context.WithTimeout(parent, smartctlTimeout)
	defer cancel()
	cmd := exec.CommandContext(ctx, bin, args...)
	// smartctl exits non-zero on failing drives (or unreadable error logs)
	// while still emitting usable JSON, so the error is only reported when
	// the output turns out to be unusable.
	output, primaryErr := cmd.Output()
	if parent.Err() != nil {
		return nil, parent.Err()
	}

	if len(output) > 0 {
		var check json.RawMessage
		if json.Unmarshal(output, &check) == nil {
			return output, nil
		}
	}

	// fallback: retry with -a without explicit --device flag
	ctx2, cancel2 := context.WithTimeout(parent, smartctlTimeout)
	defer cancel2()
	fbCmd := exec.CommandContext(ctx2, bin, "-a", "--json", fullName)
	output2, fbErr := fbCmd.Output()
	if parent.Err() != nil {
		return nil, parent.Err()
	}

	var check2 json.RawMessage
	if err := json.Unmarshal(output2, &check2); err != nil {
		if primaryErr != nil {
			return nil, fmt.Errorf("smartctl failed for %s: %w (fallback -a also produced no valid JSON)", deviceName, primaryErr)
		}
		if fbErr != nil && len(output2) == 0 {
			return nil, fmt.Errorf("smartctl fallback failed for %s: %w", deviceName, fbErr)
		}
		return nil, fmt.Errorf("smartctl produced no valid JSON for %s", deviceName)
	}

	return output2, nil
}

func (s *Scanner) RunSmartctlPlainContext(parent context.Context, deviceName, deviceType string) ([]byte, error) {
	bin := s.Config.Commands.SmartctlBin
	fullName := DevicePrefix() + deviceName
	args, err := s.smartctlArgs(deviceName, deviceType, false)
	if err != nil {
		return nil, err
	}

	ctx, cancel := context.WithTimeout(parent, smartctlTimeout)
	defer cancel()
	cmd := exec.CommandContext(ctx, bin, args...)
	combined, primaryErr := cmd.CombinedOutput()
	if parent.Err() != nil {
		return nil, parent.Err()
	}
	if len(combined) > 0 {
		return combined, nil
	}

	// fallback: -a without --device
	ctx2, cancel2 := context.WithTimeout(parent, smartctlTimeout)
	defer cancel2()
	fbCmd := exec.CommandContext(ctx2, bin, "-a", fullName)
	combined2, fbErr := fbCmd.CombinedOutput()
	if parent.Err() != nil {
		return nil, parent.Err()
	}
	if len(combined2) == 0 {
		if primaryErr != nil {
			return nil, fmt.Errorf("smartctl failed for %s: %w (fallback -a also produced no output)", deviceName, primaryErr)
		}
		if fbErr != nil {
			return nil, fmt.Errorf("smartctl plain fallback failed for %s: %w", deviceName, fbErr)
		}
		return nil, fmt.Errorf("smartctl plain produced no output for %s", deviceName)
	}

	return combined2, nil
}

// smartctlArgs keeps JSON and plain-text collection on the same command path.
// The configured arguments are shared; plain-text collection only removes JSON
// flags before adding the device-specific arguments.
func (s *Scanner) smartctlArgs(deviceName, deviceType string, includeJSON bool) ([]string, error) {
	fullName := DevicePrefix() + deviceName
	args, err := splitCommandArgs(s.Config.GetCommandMetricsSmartArgs(fullName))
	if err != nil {
		return nil, fmt.Errorf("parse SMART arguments: %w", err)
	}

	if !includeJSON {
		plainArgs := make([]string, 0, len(args))
		for _, arg := range args {
			if arg != "--json" && arg != "-j" && !strings.HasPrefix(arg, "--json=") {
				plainArgs = append(plainArgs, arg)
			}
		}
		args = plainArgs
	}

	if deviceType != "" && deviceType != "scsi" && deviceType != "ata" {
		args = append(args, "--device", deviceType)
	}
	return append(args, fullName), nil
}

// groupScannedDevices applies the configured device overrides to a scan
// result: ignored devices are dropped, typed overrides replace the scanned
// entry with one device per type (RAID disks behind a controller), and an
// override for a device the scan missed is added with the conservative
// default type "ata".
func groupScannedDevices(scanResult ScanResult, overrides []config.DeviceOverride) []ScannedDevice {
	grouped := make(map[string][]ScannedDevice)

	for _, d := range scanResult.Devices {
		devicePath := strings.ToLower(d.Name)
		deviceName := strings.TrimPrefix(d.Name, DevicePrefix())

		grouped[devicePath] = append(grouped[devicePath], ScannedDevice{
			DeviceName: deviceName,
			DeviceType: d.Type,
		})
	}

	for _, override := range overrides {
		overridePath := strings.ToLower(override.Device)

		if override.Ignore {
			delete(grouped, overridePath)
			continue
		}

		if len(override.Type) > 0 {
			var newGroup []ScannedDevice
			for _, dt := range override.Type {
				newGroup = append(newGroup, ScannedDevice{
					DeviceName: strings.TrimPrefix(overridePath, DevicePrefix()),
					DeviceType: dt,
				})
			}
			grouped[overridePath] = newGroup
		} else {
			if _, exists := grouped[overridePath]; !exists {
				grouped[overridePath] = []ScannedDevice{{
					DeviceName: strings.TrimPrefix(overridePath, DevicePrefix()),
					DeviceType: "ata",
				}}
			}
		}
	}

	var devices []ScannedDevice
	for _, group := range grouped {
		devices = append(devices, group...)
	}
	return devices
}

// fallbackDeviceIdentity scopes a path-only disk identity to the host. It is
// only used when SMART reports no serial, WWN, or logical unit identifier.
func fallbackDeviceIdentity(hostname, deviceName string) string {
	host := strings.ToLower(strings.TrimSpace(hostname))
	device := strings.ToLower(strings.TrimSpace(deviceName))
	if host == "" || host == "unknown" {
		return device
	}
	return host + ":" + device
}
