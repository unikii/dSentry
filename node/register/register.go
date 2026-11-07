package register

import (
	"context"
	"fmt"
	"github.com/unikii/dsentry/node/logutil"
	"log"

	"github.com/unikii/dsentry/node/api"
	"github.com/unikii/dsentry/node/config"
	"github.com/unikii/dsentry/node/scanner"
	smartctl "github.com/unikii/dsentry/node/smartctl"
	"github.com/unikii/dsentry/node/types"
)

// RegisterDevicesContext registers newly discovered devices with their
// identity, metadata, and one initial metrics sample.
//
// Raw SMART snapshots are deliberately not part of registration: they travel
// through the regular raw push so the hub's raw schedule and plain-text policy
// apply, and a registration cannot store the same scan twice (or fail the
// whole batch when one compressed snapshot is oversized).
func RegisterDevicesContext(
	ctx context.Context,
	apiClient *api.Client,
	stateManager *config.StateManager,
	nodeID int,
	scannedDevices []scanner.ScannedDevice,
) error {
	state, err := stateManager.Load()
	if err != nil {
		return fmt.Errorf("loading state: %w", err)
	}

	var toRegister []types.DeviceRegistration
	deviceByHash := make(map[string]scanner.ScannedDevice)
	seenHashes := make(map[string]struct{})
	stateChanged := false

	for _, d := range scannedDevices {
		hash := d.DeviceHash
		if hash == "" {
			continue
		}
		if _, seen := seenHashes[hash]; seen {
			logutil.Debugf("Skipping duplicate device hash %s", hash)
			continue
		}
		seenHashes[hash] = struct{}{}

		if existing, exists := state.Devices[hash]; exists {
			// The caller only passes devices missing from local state, so
			// this is defensive: never re-register an already-known device.
			if existing.DeviceName == "" {
				existing.DeviceName = d.DeviceName
				state.Devices[hash] = existing
				stateChanged = true
			}
			continue
		}

		// Leave the health baseline at zero for a newly discovered disk.
		// If it is already failing, the first collection sees a transition
		// and emits an alert instead of silently adopting the failure as
		// the baseline.
		state.Devices[hash] = types.DeviceState{DeviceName: d.DeviceName}
		stateChanged = true

		toRegister = append(toRegister, types.DeviceRegistration{
			DeviceHash: hash,
			MetaHash:   d.MetaHash,
			DeviceMeta: d.Meta,
		})
		deviceByHash[hash] = d
	}

	if len(toRegister) == 0 {
		if stateChanged {
			if err := stateManager.Save(state); err != nil {
				return fmt.Errorf("saving state after device discovery: %w", err)
			}
		}
		return nil
	}

	logutil.Debugf("Registering %d new devices", len(toRegister))

	for i := range toRegister {
		d := deviceByHash[toRegister[i].DeviceHash]

		if len(d.RawOutput) == 0 {
			log.Printf("Warning: no SMART JSON output for %s — registering metadata only", d.DeviceName)
			continue
		}

		parsed, err := smartctl.ParseOutput(d.RawOutput)
		if err != nil {
			log.Printf("Warning: failed to parse SMART output for %s during registration: %v", d.DeviceName, err)
			continue
		}

		_, overallThresholdStatus := smartctl.ComputeThresholdStatuses(parsed.Output, parsed.Protocol)

		if meta, ok := toRegister[i].DeviceMeta.(*smartctl.DeviceMeta); ok {
			meta.SMARTThresholdStatus = overallThresholdStatus
			updatedHash := smartctl.ComputeMetaHash(meta)
			toRegister[i].MetaHash = updatedHash
			updated := deviceByHash[toRegister[i].DeviceHash]
			updated.MetaHash = updatedHash
			deviceByHash[toRegister[i].DeviceHash] = updated
		}

		if parsed.MetricsErr != nil || parsed.Metrics == nil {
			logutil.Debugf("Metrics unavailable for %s during registration: %v", d.DeviceName, parsed.MetricsErr)
		} else {
			metricsMap, err := smartctl.MetricsToMap(parsed.Metrics)
			if err != nil {
				logutil.Debugf("Failed to convert metrics to map for %s: %v", d.DeviceName, err)
			} else {
				toRegister[i].InitialMetrics = metricsMap
			}
		}

		ds := state.Devices[toRegister[i].DeviceHash]
		ds.DeviceName = d.DeviceName
		state.Devices[toRegister[i].DeviceHash] = ds
	}

	resp, err := apiClient.RegisterDevicesContext(ctx, nodeID, toRegister)
	if err != nil {
		return fmt.Errorf("register devices API call failed: %w", err)
	}

	for _, result := range resp.Payload {
		if d, ok := deviceByHash[result.DeviceHash]; ok {
			ds := state.Devices[result.DeviceHash]
			ds.DeviceID = result.DeviceID
			ds.MetaHash = d.MetaHash
			state.Devices[result.DeviceHash] = ds
		}
	}

	if err := stateManager.Save(state); err != nil {
		return fmt.Errorf("saving state after registration: %w", err)
	}

	logutil.Debugf("Successfully registered %d devices", len(resp.Payload))
	return nil
}
