package loop

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"github.com/unikii/dsentry/node/api"
	"github.com/unikii/dsentry/node/config"
	"github.com/unikii/dsentry/node/logutil"
	"github.com/unikii/dsentry/node/register"
	"github.com/unikii/dsentry/node/scanner"
	smartctl "github.com/unikii/dsentry/node/smartctl"
	"github.com/unikii/dsentry/node/thresholds"
	"github.com/unikii/dsentry/node/types"
	"log"
	"net/http"
	"strings"
	"time"
)

// ErrFatal marks loop errors that should stop the node process (node
// deleted, push key invalid, device limit reached). The caller decides the
// exit policy; deferred cleanup runs either way.
var ErrFatal = errors.New("fatal error")

// maxOutboxEntries bounds the offline queue persisted in the state file.
// With the default 30-minute push interval this covers about six days of
// outage (288 entries).
const maxOutboxEntries = 288

// maxReplayMetricsPoints matches the hub's MAX_METRICS_PER_PUSH. A backlog
// larger than this is drained one interval at a time.
const maxReplayMetricsPoints = 5000

type PushLoop struct {
	APIClient    *api.Client
	Config       *config.Config
	StateManager *config.StateManager
	Scanner      *scanner.Scanner
	NodeID       int

	// Testing hooks; zero values fall back to production defaults.
	OfflineRetry   time.Duration // config-pull retry cadence while hub unreachable
	OfflineCadence time.Duration // minimum spacing between offline collections
}

func New(apiClient *api.Client, cfg *config.Config, stateManager *config.StateManager, scanner *scanner.Scanner, nodeID int) *PushLoop {
	return &PushLoop{
		APIClient:    apiClient,
		Config:       cfg,
		StateManager: stateManager,
		Scanner:      scanner,
		NodeID:       nodeID,
	}
}

func (l *PushLoop) offlineRetryInterval() time.Duration {
	if l.OfflineRetry > 0 {
		return l.OfflineRetry
	}
	return 60 * time.Second
}

func (l *PushLoop) offlineCadence(defaultMinutes int) time.Duration {
	if l.OfflineCadence > 0 {
		return l.OfflineCadence
	}
	if defaultMinutes < 1 {
		defaultMinutes = 1
	}
	return time.Duration(defaultMinutes) * time.Minute
}

// collectOptions carries the server-driven knobs collect() needs. They are
// kept from the last successful config pull so offline cycles behave like
// the online ones.
type collectOptions struct {
	pushRaw      bool
	pushRawPlain bool
}

type cycleData struct {
	metrics       []interface{}
	raws          map[int]types.RawEntry
	metas         []types.DeviceMetaEntry
	events        []types.DeviceEvent
	state         *types.NodeState
	statusChanged bool
}

func (l *PushLoop) RunWithContext(ctx context.Context) error {
	firstCycle := true
	pushInterval := 30
	nextPushTime := time.Now()
	lastOpts := collectOptions{pushRawPlain: true}
	var lastOfflineCollect time.Time

	for {
		select {
		case <-ctx.Done():
			log.Println("Push loop stopped")
			return ctx.Err()
		default:
		}

		if !firstCycle {
			if err := waitUntil(ctx, nextPushTime); err != nil {
				return ctx.Err()
			}
		}

		serverConfig, err := l.APIClient.GetConfigContext(ctx, l.NodeID)
		if err != nil {
			log.Printf("Failed to pull config: %v", err)
			if isFatalStatus(err, types.StatusNodeNotRegistered) || isAuthError(err) {
				return fmt.Errorf("%w: node has been deleted or push key is invalid: %v", ErrFatal, err)
			}

			// Hub unreachable: keep collecting locally on the server's
			// schedule so history survives the outage via the outbox.
			if time.Since(lastOfflineCollect) >= l.offlineCadence(pushInterval) {
				lastOfflineCollect = time.Now()
				if data, collectErr := l.collect(ctx, lastOpts); collectErr != nil {
					log.Printf("Warning: offline collection failed: %v", collectErr)
				} else {
					l.deliverOffline(data)
				}
			}

			if err := sleepWithClockCheck(ctx, l.offlineRetryInterval()); err != nil {
				return ctx.Err()
			}
			continue
		}

		pushInterval = serverConfig.Payload.PushInterval
		if pushInterval <= 0 {
			pushInterval = 30
		}
		nextPushTime, isDue := computeNextPush(
			pushInterval,
			serverConfig.Payload.LastMetricsPush,
			serverConfig.Payload.ServerTime,
		)
		lastOpts = collectOptions{
			pushRaw:      serverConfig.Payload.PushRaw,
			pushRawPlain: serverConfig.Payload.PushRawPlain,
		}

		logutil.Debugf("Config pulled: interval=%d min, push_raw=%v, push_raw_plain=%v, last_metrics_push=%s, server_time=%s, due=%v",
			pushInterval,
			serverConfig.Payload.PushRaw,
			serverConfig.Payload.PushRawPlain,
			formatOptionalTimestamp(serverConfig.Payload.LastMetricsPush),
			serverConfig.Payload.ServerTime,
			isDue)

		if firstCycle {
			// A due cycle registers devices itself inside collect(); skipping
			// the standalone registration avoids scanning every disk twice at
			// startup.
			if !isDue {
				if err := l.initialRegister(ctx); err != nil {
					if isFatalStatus(err, types.StatusNodeNotRegistered) ||
						isFatalStatus(err, types.StatusExceedsDeviceLimit) || isAuthError(err) {
						return fmt.Errorf("%w: %v", ErrFatal, err)
					}
					log.Printf("Initial device registration failed: %v", err)
				}
			}
			firstCycle = false
		}

		if !isDue {
			// Sleep until the scheduled push time. waitUntil is wall-clock
			// aware, so a suspend/resume while waiting forces an immediate
			// config refresh instead of sleeping through the sleep period.
			logNextPush(nextPushTime)
			// The metrics interval has not elapsed, so only flush
			// non-metrics entries; replaying metrics now would be rejected.
			l.flushOutbox(ctx, false, true)
			if err := waitUntil(ctx, nextPushTime); err != nil {
				return ctx.Err()
			}
			continue
		}

		// Flush non-metrics first, but leave raws queued: the hub accepts at
		// most one raw push per raw interval, so flushing an older snapshot
		// here would consume the slot and make the fresh snapshot collected
		// below be rejected (leaving raw data permanently one cycle behind).
		// Raws are superseded by the live push in deliver().
		l.flushOutbox(ctx, false, false)

		if err := l.runCycle(ctx, serverConfig); err != nil {
			if isFatalStatus(err, types.StatusExceedsDeviceLimit) || isAuthError(err) {
				return fmt.Errorf("%w: %v", ErrFatal, err)
			}
			log.Printf("Push cycle failed: %v", err)
			// No live payload was produced, so the interval's metrics slot is
			// free; use it to keep a backlog draining through collection errors.
			l.flushOutbox(ctx, true, true)
		}

		logNextPush(nextPushTime)
		// The live cycle may have queued events/metas; retry those now.
		// Metrics and raws queued by the live cycle wait for the next
		// interval (raws retry on the next non-due cycle).
		l.flushOutbox(ctx, false, false)

		// A due cycle may produce no metrics, so the server timestamp may not
		// advance. Keep the local schedule as the retry backoff in that case.
		if err := waitUntil(ctx, nextPushTime); err != nil {
			return ctx.Err()
		}
	}
}

func isFatalStatus(err error, code int) bool {
	return api.APIStatus(err) == code
}

func isAuthError(err error) bool {
	status := api.HTTPStatus(err)
	return status == 401 || status == 403
}

func formatOptionalTimestamp(value *string) string {
	if value == nil {
		return "<nil>"
	}
	return *value
}

const (
	clockPollInterval      = 5 * time.Second
	clockJumpThreshold     = 10 * time.Second
	clockJumpRecoveryDelay = 5 * time.Second
)

func waitUntil(ctx context.Context, until time.Time) error {
	return waitUntilWithClock(ctx, until, func() int64 { return time.Now().UnixNano() })
}

func waitUntilWithClock(ctx context.Context, until time.Time, wallNow func() int64) error {
	// Sleep on the monotonic clock so NTP adjustments do not distort the
	// schedule, but watch the wall clock so that a suspend/resume jump
	// (larger than clockJumpThreshold) forces a config refresh after a short
	// recovery delay for network services such as VPN and DNS.
	lastWall := wallNow()
	for {
		remaining := time.Until(until)
		if remaining <= 0 {
			return nil
		}

		nowWall := wallNow()
		if delta := nowWall - lastWall; delta > clockJumpThreshold.Nanoseconds() || delta < -clockJumpThreshold.Nanoseconds() {
			log.Printf("Detected wall-clock jump of %v (likely suspend/resume), waiting %s before config refresh", time.Duration(delta).Round(time.Second), clockJumpRecoveryDelay)
			timer := time.NewTimer(clockJumpRecoveryDelay)
			select {
			case <-ctx.Done():
				if !timer.Stop() {
					select {
					case <-timer.C:
					default:
					}
				}
				return ctx.Err()
			case <-timer.C:
				return nil
			}
		}
		lastWall = nowWall

		wait := clockPollInterval
		if remaining < wait {
			wait = remaining
		}
		timer := time.NewTimer(wait)
		select {
		case <-ctx.Done():
			if !timer.Stop() {
				select {
				case <-timer.C:
				default:
				}
			}
			return ctx.Err()
		case <-timer.C:
		}
	}
}

func sleepWithClockCheck(ctx context.Context, d time.Duration) error {
	if d <= 0 {
		return nil
	}
	deadlineWall := time.Now().UnixNano() + int64(d)
	lastWall := time.Now().UnixNano()
	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		default:
		}

		nowWall := time.Now().UnixNano()
		if nowWall >= deadlineWall {
			return nil
		}
		if delta := nowWall - lastWall; delta > clockJumpThreshold.Nanoseconds() || delta < -clockJumpThreshold.Nanoseconds() {
			return nil
		}
		lastWall = nowWall

		wait := clockPollInterval
		if remaining := time.Duration(deadlineWall - nowWall); remaining < wait {
			wait = remaining
		}
		timer := time.NewTimer(wait)
		select {
		case <-ctx.Done():
			if !timer.Stop() {
				select {
				case <-timer.C:
				default:
				}
			}
			return ctx.Err()
		case <-timer.C:
		}
	}
}

const pushSafetyMargin = 5 * time.Second

func computeNextPush(pushInterval int, lastMetricsPush *string, serverTime string) (nextPush time.Time, isDue bool) {
	interval := time.Duration(pushInterval) * time.Minute
	if lastMetricsPush == nil || serverTime == "" {
		return time.Now().Add(interval).Add(pushSafetyMargin), true
	}

	lastPush, err := time.Parse(time.RFC3339Nano, *lastMetricsPush)
	if err != nil {
		return time.Now().Add(interval).Add(pushSafetyMargin), true
	}
	serverNow, err := time.Parse(time.RFC3339Nano, serverTime)
	if err != nil {
		return time.Now().Add(interval).Add(pushSafetyMargin), true
	}

	elapsed := serverNow.Sub(lastPush)
	if elapsed < 0 {
		return time.Now().Add(interval).Add(pushSafetyMargin), true
	}
	if elapsed >= interval {
		return time.Now().Add(interval).Add(pushSafetyMargin), true
	}
	return time.Now().Add(interval - elapsed).Add(pushSafetyMargin), false
}

func logNextPush(nextPushTime time.Time) {
	remaining := time.Until(nextPushTime)
	if remaining < 0 {
		remaining = 0
	}
	log.Printf("Next push at %s (in %s)", nextPushTime.Format("15:04:05"), formatDuration(remaining))
}

func formatDuration(d time.Duration) string {
	if d < time.Minute {
		return fmt.Sprintf("%ds", int(d.Seconds()))
	}
	if d < time.Hour {
		m := int(d.Minutes())
		s := int(d.Seconds()) % 60
		if s > 0 {
			return fmt.Sprintf("%dm%ds", m, s)
		}
		return fmt.Sprintf("%dm", m)
	}
	h := int(d.Hours())
	m := int(d.Minutes()) % 60
	if m > 0 {
		return fmt.Sprintf("%dh%dm", h, m)
	}
	return fmt.Sprintf("%dh", h)
}

func (l *PushLoop) scanAndPopulate(ctx context.Context) ([]scanner.ScannedDevice, error) {
	scannedDevices, err := l.Scanner.RunSmartctlScanContext(ctx)
	if err != nil {
		return nil, fmt.Errorf("scan: %w", err)
	}

	scannedDevices, err = l.Scanner.PopulateDeviceInfoContext(ctx, scannedDevices)
	if err != nil {
		if ctx.Err() != nil {
			return nil, ctx.Err()
		}
		log.Printf("Warning: populating device info: %v", err)
		return scannedDevices, nil
	}

	return scannedDevices, nil
}

// registerNewDevices registers scanned devices that are missing from the
// node state — this is what makes disks plugged in after startup visible
// to the hub. Returns true when at least one device was registered.
func (l *PushLoop) registerNewDevices(ctx context.Context, scannedDevices []scanner.ScannedDevice, state *types.NodeState) (bool, error) {
	var newDevices []scanner.ScannedDevice
	for _, d := range scannedDevices {
		if d.DeviceHash == "" {
			continue
		}
		if _, known := state.Devices[d.DeviceHash]; !known {
			newDevices = append(newDevices, d)
		}
	}
	if len(newDevices) == 0 {
		return false, nil
	}

	log.Printf("Discovered %d new device(s), registering", len(newDevices))
	if err := register.RegisterDevicesContext(ctx, l.APIClient, l.StateManager, l.NodeID, newDevices); err != nil {
		return false, fmt.Errorf("register: %w", err)
	}
	return true, nil
}

// initialRegister registers devices present at startup so the first push
// cycle knows their hub device IDs.
func (l *PushLoop) initialRegister(ctx context.Context) error {
	scannedDevices, err := l.scanAndPopulate(ctx)
	if err != nil {
		return err
	}

	state, err := l.StateManager.Load()
	if err != nil {
		return fmt.Errorf("load state: %w", err)
	}

	_, err = l.registerNewDevices(ctx, scannedDevices, state)
	return err
}

func (l *PushLoop) compressRawOutput(
	ctx context.Context,
	device *scanner.ScannedDevice,
	includePlain bool,
) ([]byte, error) {
	var plainOutput []byte
	if includePlain {
		var err error
		plainOutput, err = l.Scanner.RunSmartctlPlainContext(ctx, device.DeviceName, device.DeviceType)
		if err != nil {
			logutil.Debugf("Failed to get plain SMART data for %s: %v", device.DeviceName, err)
		}
	}

	return smartctl.CompressRawOutput(device.RawOutput, plainOutput)
}

func (l *PushLoop) runCycle(ctx context.Context, serverConfig *types.ConfigResponse) error {
	data, err := l.collect(ctx, collectOptions{
		pushRaw:      serverConfig.Payload.PushRaw,
		pushRawPlain: serverConfig.Payload.PushRawPlain,
	})
	if err != nil {
		return err
	}
	l.deliver(ctx, data)
	return nil
}

// collect scans the drives and builds everything the cycle wants to send:
// metrics, raw outputs, changed metadata, and status-change events. It
// touches no network, so it runs unchanged while the hub is unreachable.
func (l *PushLoop) collect(ctx context.Context, opts collectOptions) (*cycleData, error) {
	scannedDevices, err := l.scanAndPopulate(ctx)
	if err != nil {
		return nil, err
	}

	state, err := l.StateManager.Load()
	if err != nil {
		return nil, fmt.Errorf("load state: %w", err)
	}

	data := &cycleData{state: state}

	// Register disks that appeared since startup (hot-plug), then pick up
	// their device IDs before building this cycle's payloads.
	registered, regErr := l.registerNewDevices(ctx, scannedDevices, state)
	if regErr != nil {
		// A newly attached disk cannot be registered while the hub is
		// unreachable, but that must not stop us from collecting the disks
		// that already have device IDs. The new disk is retried next cycle.
		log.Printf("Warning: registering new devices failed, continuing with known devices: %v", regErr)
	} else if registered {
		if state, err = l.StateManager.Load(); err != nil {
			return nil, fmt.Errorf("reload state: %w", err)
		}
		data.state = state
	}

	if len(state.Devices) == 0 {
		logutil.Debugln("No registered devices — skipping push cycle")
		return data, nil
	}

	raws := make(map[int]types.RawEntry)
	devicesByHash := make(map[string]*scanner.ScannedDevice)
	for i := range scannedDevices {
		devicesByHash[scannedDevices[i].DeviceHash] = &scannedDevices[i]
	}

	collectedAtNow := func() string { return time.Now().UTC().Format(time.RFC3339) }

	for deviceHash, devState := range state.Devices {
		device := devicesByHash[deviceHash]
		if device == nil {
			// The disk disappeared from the scan. Emit one event per
			// transition so SMART health no longer fails silently, and do
			// not keep inventing events every cycle while it stays missing.
			if !devState.Missing {
				devState.Missing = true
				state.Devices[deviceHash] = devState
				data.statusChanged = true
				data.events = append(data.events, types.DeviceEvent{
					DeviceHash:  deviceHash,
					DeviceID:    devState.DeviceID,
					EventType:   types.EventTypeDeviceMissing,
					CollectedAt: collectedAtNow(),
					Summary:     "Device was not detected in the latest scan",
				})
				log.Printf("Warning: device %s (%s) is missing from the scan", devState.DeviceName, deviceHash)
			} else {
				logutil.Debugf("Device %s not found in current scan — still missing", deviceHash)
			}
			continue
		}

		if devState.Missing {
			devState.Missing = false
			state.Devices[deviceHash] = devState
			data.statusChanged = true
			data.events = append(data.events, types.DeviceEvent{
				DeviceHash:  deviceHash,
				DeviceID:    devState.DeviceID,
				EventType:   types.EventTypeDeviceOnline,
				CollectedAt: collectedAtNow(),
				Summary:     "Device is visible in the scan again",
			})
		}

		collectedAt := collectedAtNow()

		if len(device.RawOutput) == 0 {
			logutil.Debugf("No raw output for device %s — skipping", deviceHash)
			continue
		}

		parsed, err := smartctl.ParseOutput(device.RawOutput)
		if err != nil {
			log.Printf("Warning: failed to parse SMART output for %s (type=%s, raw_bytes=%d): %v",
				device.DeviceName, device.DeviceType, len(device.RawOutput), err)
			if opts.pushRaw {
				rawData, compressErr := l.compressRawOutput(ctx, device, opts.pushRawPlain)
				if compressErr != nil {
					logutil.Debugf("Failed to compress raw output for %s: %v", device.DeviceName, compressErr)
				} else {
					raws[devState.DeviceID] = types.RawEntry{Data: rawData, CollectedAt: collectedAt}
				}
			}
			continue
		}

		// Metrics are optional: a parse failure above still yields status and
		// metadata, so a failing disk is never silently ignored merely
		// because its attribute/health log layout is unexpected.
		if parsed.MetricsErr != nil {
			log.Printf("Warning: SMART output parsed for %s but metrics are unavailable: %v",
				device.DeviceName, parsed.MetricsErr)
		} else if parsed.Metrics != nil {
			parsed.Metrics.DeviceHash = deviceHash
			metricsMap, err := smartctl.MetricsToMap(parsed.Metrics)
			if err != nil {
				logutil.Debugf("Failed to convert metrics to map for %s: %v", device.DeviceName, err)
			} else {
				// Let the hub stamp each point with its real collection time;
				// queued (outbox) pushes would otherwise be recorded at flush time.
				metricsMap["TimestampUTC"] = collectedAt
				data.metrics = append(data.metrics, metricsMap)
			}
		}

		currentSmartStatus := smartctl.ComputeSmartStatus(parsed.Output)
		attrStatuses, overallThresholdStatus := smartctl.ComputeThresholdStatuses(parsed.Output, parsed.Protocol)

		if currentSmartStatus != devState.SmartStatus || overallThresholdStatus != devState.ThresholdStatus {
			data.statusChanged = true

			rawData, compressErr := l.compressRawOutput(ctx, device, true)
			if compressErr != nil {
				logutil.Debugf("Failed to compress raw output for %s event, falling back to uncompressed JSON: %v", device.DeviceName, compressErr)
				rawData, _ = smartctl.CompressRawOutput(device.RawOutput, nil)
			}
			if rawData == nil {
				logutil.Debugf("Warning: no raw data for %s event", device.DeviceName)
			}

			if currentSmartStatus == 1 && devState.SmartStatus != 1 {
				data.events = append(data.events, types.DeviceEvent{
					DeviceHash:  deviceHash,
					DeviceID:    devState.DeviceID,
					EventType:   types.EventTypeSmartFail,
					CollectedAt: collectedAt,
					Summary:     thresholds.GenerateThresholdSummary(attrStatuses),
					RawData:     rawData,
				})
			}
			if currentSmartStatus == 0 && devState.SmartStatus == 1 {
				data.events = append(data.events, types.DeviceEvent{
					DeviceHash:  deviceHash,
					DeviceID:    devState.DeviceID,
					EventType:   types.EventTypeSmartSuccess,
					CollectedAt: collectedAt,
					RawData:     rawData,
				})
			}
			if overallThresholdStatus == thresholds.SMARTThresholdStatusWarning && devState.ThresholdStatus != thresholds.SMARTThresholdStatusWarning {
				data.events = append(data.events, types.DeviceEvent{
					DeviceHash:  deviceHash,
					DeviceID:    devState.DeviceID,
					EventType:   types.EventTypeThresholdWarning,
					CollectedAt: collectedAt,
					Summary:     thresholds.GenerateThresholdSummary(attrStatuses),
					RawData:     rawData,
				})
			}
			if overallThresholdStatus == thresholds.SMARTThresholdStatusFailed && devState.ThresholdStatus != thresholds.SMARTThresholdStatusFailed {
				data.events = append(data.events, types.DeviceEvent{
					DeviceHash:  deviceHash,
					DeviceID:    devState.DeviceID,
					EventType:   types.EventTypeThresholdCritical,
					CollectedAt: collectedAt,
					Summary:     thresholds.GenerateThresholdSummary(attrStatuses),
					RawData:     rawData,
				})
			}

			devState.SmartStatus = currentSmartStatus
			devState.ThresholdStatus = overallThresholdStatus
			state.Devices[deviceHash] = devState
		}

		meta, metaErr := parsed.Parser.ParseMeta(parsed.Output)
		if metaErr == nil && meta != nil {
			meta.DeviceHash = deviceHash
			meta.DeviceName = device.DeviceName
			meta.SMARTThresholdStatus = overallThresholdStatus
			currentMetaHash := smartctl.ComputeMetaHash(meta)
			if currentMetaHash != devState.MetaHash {
				data.metas = append(data.metas, types.DeviceMetaEntry{
					DeviceHash: deviceHash,
					MetaHash:   currentMetaHash,
					DeviceMeta: meta,
				})
			}
		}

		if opts.pushRaw {
			rawData, compressErr := l.compressRawOutput(ctx, device, opts.pushRawPlain)
			if compressErr != nil {
				logutil.Debugf("Failed to compress raw output for %s: %v", device.DeviceName, compressErr)
				continue
			}
			raws[devState.DeviceID] = types.RawEntry{Data: rawData, CollectedAt: collectedAt}
		}

		if l.Config.Commands.SmartctlWait > 0 {
			if err := sleepWithClockCheck(ctx, time.Duration(l.Config.Commands.SmartctlWait)*time.Second); err != nil {
				return nil, err
			}
		}
	}

	if len(data.metrics) == 0 && len(state.Devices) > 0 {
		log.Printf("Warning: no metrics collected (registered_devices=%d, scanned_devices=%d)", len(state.Devices), len(scannedDevices))
	}

	data.raws = raws
	return data, nil
}

// deliver pushes a collected cycle to the hub; anything that fails to send
// is persisted in the state outbox instead of being dropped.
func (l *PushLoop) deliver(ctx context.Context, data *cycleData) {
	outboxChanged := false

	if data.statusChanged {
		if len(data.events) > 0 {
			if err := l.APIClient.PushEventsContext(ctx, l.NodeID, data.events); err != nil {
				log.Printf("Warning: push events failed, queueing %d event(s): %v", len(data.events), err)
				l.enqueueOutbox(data.state, types.OutboxKindEvents, data.events)
				outboxChanged = true
			} else {
				logutil.Debugln("Events pushed successfully")
			}
		}
		// Save the new statuses regardless: queued events are durable in the
		// outbox, so the transition must not be re-detected and re-sent.
		if err := l.StateManager.Save(data.state); err != nil {
			log.Printf("Warning: failed to save state after status change: %v", err)
		}
	}

	if len(data.metrics) > 0 || hasQueuedMetrics(data.state) {
		batch, remaining, liveIncluded, dropped := buildMetricsBatch(
			data.state, data.metrics,
		)
		if dropped > 0 {
			log.Printf("Warning: dropped %d corrupt outbox metrics entry(s)", dropped)
		}

		if len(batch) == 0 {
			// Only corrupt entries were present; drop them from the outbox.
			data.state.Outbox = remaining
			if !liveIncluded && len(data.metrics) > 0 {
				l.enqueueOutbox(data.state, types.OutboxKindMetrics, data.metrics)
			}
			outboxChanged = true
		} else {
			logutil.Debugf(
				"Pushing %d metrics (%d live point(s) included=%v)",
				len(batch), len(data.metrics), liveIncluded,
			)
			if err := l.APIClient.PushMetricsContext(ctx, l.NodeID, batch); err != nil {
				log.Printf("Warning: push metrics failed, queueing: %v", err)
				if api.APIStatus(err) == types.StatusNoKnownDevices {
					// The hub has none of our device hashes (e.g. its device
					// table was restored without them). Clear the local IDs so
					// the next collection re-registers every scanned disk;
					// queued points carry hashes and resolve after that.
					log.Printf("Hub reports no known devices — clearing local device IDs and re-registering next cycle")
					data.state.Devices = make(map[string]types.DeviceState)
				}
				// Keep the queued entries intact and append the live points.
				if len(data.metrics) > 0 {
					l.enqueueOutbox(data.state, types.OutboxKindMetrics, data.metrics)
				}
				outboxChanged = true
			} else {
				data.state.Outbox = remaining
				if !liveIncluded && len(data.metrics) > 0 {
					l.enqueueOutbox(data.state, types.OutboxKindMetrics, data.metrics)
				}
				outboxChanged = true
				logutil.Debugln("Metrics pushed successfully")
			}
		}
	}

	if len(data.metas) > 0 {
		logutil.Debugf("Pushing %d meta updates", len(data.metas))
		results, err := l.APIClient.PushMetasContext(ctx, l.NodeID, data.metas)
		if err != nil {
			log.Printf("Warning: push metas failed, queueing: %v", err)
			l.enqueueOutbox(data.state, types.OutboxKindMetas, data.metas)
			outboxChanged = true
		} else {
			applied := filterUpdatedMetas(data.metas, results)
			applyMetaHashes(data.state, applied)
			if len(applied) > 0 {
				// Persist the advanced hashes; otherwise a meta-only cycle
				// would re-send the same update on every collection.
				outboxChanged = true
			}
			if len(applied) < len(data.metas) {
				logutil.Debugf("Hub skipped %d meta update(s) (archived/unknown); they will be retried", len(data.metas)-len(applied))
			}
			logutil.Debugln("Meta updates pushed successfully")
		}
	}

	if len(data.raws) > 0 {
		logutil.Debugf("Pushing %d raw outputs", len(data.raws))
		if err := l.APIClient.PushRawsContext(ctx, l.NodeID, data.raws); err != nil {
			log.Printf("Warning: push raws failed, queueing: %v", err)
			l.enqueueOutbox(data.state, types.OutboxKindRaws, data.raws)
			outboxChanged = true
		} else {
			// The live snapshots are newer than anything still queued for the
			// same devices, and the hub accepted them just now. Drop only the
			// superseded entries so they cannot occupy the next raw slot ahead
			// of a fresh snapshot (raws for devices missing from this push are
			// kept).
			if dropSupersededRaws(data.state, data.raws) {
				outboxChanged = true
			}
			logutil.Debugln("Raw outputs pushed successfully")
		}
	}

	if outboxChanged {
		if err := l.StateManager.Save(data.state); err != nil {
			log.Printf("Warning: failed to save state with queued pushes: %v", err)
		}
	}
}

// deliverOffline is deliver's counterpart for cycles that ran while the hub
// was unreachable: everything goes to the outbox.
func (l *PushLoop) deliverOffline(data *cycleData) {
	outboxChanged := false

	if len(data.events) > 0 {
		l.enqueueOutbox(data.state, types.OutboxKindEvents, data.events)
		outboxChanged = true
	}
	if len(data.metrics) > 0 {
		l.enqueueOutbox(data.state, types.OutboxKindMetrics, data.metrics)
		outboxChanged = true
	}
	if len(data.metas) > 0 {
		l.enqueueOutbox(data.state, types.OutboxKindMetas, data.metas)
		outboxChanged = true
	}
	if len(data.raws) > 0 {
		l.enqueueOutbox(data.state, types.OutboxKindRaws, data.raws)
		outboxChanged = true
	}

	if data.statusChanged || outboxChanged {
		if err := l.StateManager.Save(data.state); err != nil {
			log.Printf("Warning: failed to save state during offline collection: %v", err)
		}
	}
}

func hasQueuedMetrics(state *types.NodeState) bool {
	for _, entry := range state.Outbox {
		if entry.Kind == types.OutboxKindMetrics {
			return true
		}
	}
	return false
}

// buildMetricsBatch merges queued metrics with the live points into at most
// one hub-sized POST. Queued points come first so a backlog keeps priority;
// live points are included only when every queued entry fit and there is
// room left. The returned outbox excludes fully consumed entries.
func buildMetricsBatch(
	state *types.NodeState, live []interface{},
) (batch []interface{}, remaining []types.OutboxEntry, liveIncluded bool, dropped int) {
	type queuedMetric struct {
		entry  types.OutboxEntry
		points []interface{}
	}
	var queued []queuedMetric
	remaining = make([]types.OutboxEntry, 0, len(state.Outbox))
	for _, entry := range state.Outbox {
		if entry.Kind != types.OutboxKindMetrics {
			remaining = append(remaining, entry)
			continue
		}
		var points []interface{}
		if err := json.Unmarshal(entry.Payload, &points); err != nil {
			log.Printf("Warning: dropping corrupt outbox metrics entry: %v", err)
			dropped++
			continue
		}
		queued = append(queued, queuedMetric{entry: entry, points: points})
	}

	batch = make([]interface{}, 0, maxReplayMetricsPoints)
	consumed := 0
	for _, item := range queued {
		if len(batch) > 0 && len(batch)+len(item.points) > maxReplayMetricsPoints {
			break
		}
		batch = append(batch, item.points...)
		consumed++
	}
	for _, item := range queued[consumed:] {
		remaining = append(remaining, item.entry)
	}

	if consumed == len(queued) {
		switch {
		case len(live) == 0:
			liveIncluded = true
		case len(batch)+len(live) <= maxReplayMetricsPoints:
			batch = append(batch, live...)
			liveIncluded = true
		}
	}
	return batch, remaining, liveIncluded, dropped
}

func (l *PushLoop) enqueueOutbox(state *types.NodeState, kind string, payload interface{}) {
	data, err := json.Marshal(payload)
	if err != nil {
		log.Printf("Warning: outbox marshal failed for %s: %v", kind, err)
		return
	}

	if kind == types.OutboxKindRaws {
		// Keep only the latest raw per outage — older raws have no
		// diagnostic value once a newer snapshot exists.
		kept := make([]types.OutboxEntry, 0, len(state.Outbox))
		for _, e := range state.Outbox {
			if e.Kind != kind {
				kept = append(kept, e)
			}
		}
		state.Outbox = kept
	}

	if kind == types.OutboxKindMetas {
		// Deduplicate per device hash and keep a single queued meta entry:
		// an offline cycle re-collects the same metadata every cadence, which
		// used to fill the capped outbox with identical entries. The newest
		// payload wins.
		var incoming []types.DeviceMetaEntry
		if err := json.Unmarshal(data, &incoming); err == nil {
			merged := make(map[string]types.DeviceMetaEntry)
			order := make([]string, 0, len(incoming))
			add := func(m types.DeviceMetaEntry) {
				if _, seen := merged[m.DeviceHash]; !seen {
					order = append(order, m.DeviceHash)
				}
				merged[m.DeviceHash] = m
			}
			kept := make([]types.OutboxEntry, 0, len(state.Outbox))
			for _, e := range state.Outbox {
				if e.Kind != kind {
					kept = append(kept, e)
					continue
				}
				var queued []types.DeviceMetaEntry
				if err := json.Unmarshal(e.Payload, &queued); err != nil {
					// Let flushOutbox drop the corrupt entry.
					kept = append(kept, e)
					continue
				}
				for _, m := range queued {
					add(m)
				}
			}
			for _, m := range incoming {
				add(m)
			}
			state.Outbox = kept
			if len(order) > 0 {
				combined := make([]types.DeviceMetaEntry, 0, len(order))
				for _, hash := range order {
					combined = append(combined, merged[hash])
				}
				if mergedPayload, err := json.Marshal(combined); err == nil {
					data = mergedPayload
				}
			}
		}
	}

	state.Outbox = append(state.Outbox, types.OutboxEntry{
		Kind:    kind,
		At:      time.Now().UTC().Format(time.RFC3339),
		Payload: data,
	})

	if len(state.Outbox) > maxOutboxEntries {
		dropped := len(state.Outbox) - maxOutboxEntries
		state.Outbox = state.Outbox[dropped:]
		log.Printf("Warning: outbox full — dropped %d oldest queued item(s)", dropped)
	}
}

// flushOutbox re-sends queued pushes after the hub comes back. Metrics are
// batched into a single POST because the hub admits only one metrics push
// per interval; every point carries its own TimestampUTC so history keeps
// its original timestamps.
//
// Failures are classified (see classifyOutboxFailure): transient problems
// pause the flush until the next cycle, while a hub that rejects the
// payload itself (HTTP 4xx) lets flushing continue past the rejected entry,
// so one poison payload can never wedge the queue behind it. Poison entries
// are quarantined — dropped with a loud log — after outboxMaxAttempts
// consecutive rejections, keeping the capped outbox from silently dropping
// newer, deliverable data in their place.
func (l *PushLoop) flushOutbox(ctx context.Context, includeMetrics bool, includeRaws bool) bool {
	state, err := l.StateManager.Load()
	if err != nil {
		log.Printf("Warning: outbox flush skipped (load state): %v", err)
		return false
	}
	if len(state.Outbox) == 0 {
		return false
	}

	outbox := state.Outbox
	// kept accumulates every entry that must survive this flush, in order;
	// on a transient pause the not-yet-scanned tail is appended before the
	// (labeled) break, so `state.Outbox = kept` is valid on every exit path.
	kept := make([]types.OutboxEntry, 0, len(outbox))
	flushed := 0
	quarantined := 0
	dropped := 0
	poisonHits := 0
	metricsSent := false
	metricsFlushed := false
	reregister := false
	var flushedMetas []types.DeviceMetaEntry

flushLoop:
	for i := 0; i < len(outbox); {
		entry := outbox[i]
		switch entry.Kind {
		case types.OutboxKindMetrics:
			// Metrics are interval-limited. Send at most one batch per call,
			// and only when the caller says the interval slot is available.
			if !includeMetrics || metricsSent {
				kept = append(kept, entry)
				i++
				continue
			}

			// Batch a consecutive run, capped at the hub's per-push point
			// limit so a long outage can drain over several intervals.
			var batch []interface{}
			group := make([]types.OutboxEntry, 0, 8)
			j := i
			for ; j < len(outbox) && outbox[j].Kind == types.OutboxKindMetrics; j++ {
				var points []interface{}
				if err := json.Unmarshal(outbox[j].Payload, &points); err != nil {
					log.Printf("Warning: dropping corrupt outbox metrics entry: %v", err)
					dropped++
					continue
				}
				if len(batch) > 0 && len(batch)+len(points) > maxReplayMetricsPoints {
					break
				}
				batch = append(batch, points...)
				group = append(group, outbox[j])
			}

			if len(group) > 0 {
				if err := l.APIClient.PushMetricsContext(ctx, l.NodeID, batch); err != nil {
					metricsSent = true
					if api.APIStatus(err) == types.StatusNoKnownDevices {
						log.Printf("Hub reports no known devices during outbox flush — re-registering next cycle")
						reregister = true
					}
					if classifyOutboxFailure(err) == outboxPoison {
						kept = append(kept, l.notePoisonEntries(group, err, &quarantined, &poisonHits)...)
						i = j
						continue
					}
					log.Printf("Outbox flush paused (metrics): %v", err)
					kept = append(kept, group...)
					kept = append(kept, outbox[j:]...)
					break flushLoop
				}
				flushed += len(group)
				metricsSent = true
				metricsFlushed = true
			}
			i = j

		case types.OutboxKindEvents, types.OutboxKindMetas, types.OutboxKindRaws:
			if entry.Kind == types.OutboxKindRaws && !includeRaws {
				kept = append(kept, entry)
				i++
				continue
			}
			var err error
			switch entry.Kind {
			case types.OutboxKindEvents:
				var events []types.DeviceEvent
				err = json.Unmarshal(entry.Payload, &events)
				if err == nil {
					err = l.APIClient.PushEventsContext(ctx, l.NodeID, events)
				}
			case types.OutboxKindMetas:
				var metas []types.DeviceMetaEntry
				err = json.Unmarshal(entry.Payload, &metas)
				if err == nil {
					var results []types.MetaPushResult
					results, err = l.APIClient.PushMetasContext(ctx, l.NodeID, metas)
					if err == nil {
						// Only entries the hub actually applied advance the
						// local hash; archived devices are skipped and retried.
						flushedMetas = append(flushedMetas, filterUpdatedMetas(metas, results)...)
					}
				}
			case types.OutboxKindRaws:
				var raws map[int]types.RawEntry
				err = json.Unmarshal(entry.Payload, &raws)
				if err == nil {
					err = l.APIClient.PushRawsContext(ctx, l.NodeID, raws)
				}
			}

			if err != nil && isCorruptOutboxPayload(err) {
				log.Printf("Warning: dropping corrupt outbox %s entry: %v", entry.Kind, err)
				dropped++
				i++
				continue
			}

			if err != nil {
				if classifyOutboxFailure(err) == outboxPoison {
					entry.Attempts++
					poisonHits++
					if entry.Attempts >= outboxMaxAttempts {
						quarantined++
						log.Printf("Warning: quarantining %s outbox entry from %s after %d rejections: %v",
							entry.Kind, entry.At, outboxMaxAttempts, err)
					} else {
						log.Printf("%s outbox entry from %s rejected by hub (attempt %d/%d): %v",
							entry.Kind, entry.At, entry.Attempts, outboxMaxAttempts, err)
						kept = append(kept, entry)
					}
					i++
					continue
				}
				log.Printf("Outbox flush paused (%s): %v", entry.Kind, err)
				kept = append(kept, entry)
				kept = append(kept, outbox[i+1:]...)
				break flushLoop
			}

			i++
			flushed++

		default:
			log.Printf("Warning: dropping outbox entry with unknown kind %q", entry.Kind)
			dropped++
			i++
		}
	}

	if flushed == 0 && quarantined == 0 && dropped == 0 && poisonHits == 0 && !reregister {
		return false
	}

	if reregister {
		state.Devices = make(map[string]types.DeviceState)
	}
	state.Outbox = kept
	if err := l.StateManager.Save(state); err != nil {
		log.Printf("Warning: failed to save state after outbox flush: %v", err)
		return false
	}
	if flushed > 0 {
		log.Printf("Flushed %d queued item(s) to the hub", flushed)
	}
	if quarantined > 0 {
		log.Printf("Quarantined %d undeliverable outbox item(s)", quarantined)
	}

	if len(flushedMetas) > 0 {
		if s, err := l.StateManager.Load(); err == nil {
			applyMetaHashes(s, flushedMetas)
			if err := l.StateManager.Save(s); err != nil {
				log.Printf("Warning: failed to save state after meta flush: %v", err)
			}
		}
	}
	return metricsFlushed
}

// outboxMaxAttempts is how many consecutive hard (HTTP 4xx) rejections an
// outbox entry survives before it is quarantined.
const outboxMaxAttempts = 5

// notePoisonEntries counts a hard rejection against every entry in a
// metrics batch and returns the entries that are still under the
// quarantine threshold, in order.
func (l *PushLoop) notePoisonEntries(group []types.OutboxEntry, cause error, quarantined *int, poisonHits *int) []types.OutboxEntry {
	survivors := make([]types.OutboxEntry, 0, len(group))
	for idx := range group {
		group[idx].Attempts++
		*poisonHits++
		if group[idx].Attempts >= outboxMaxAttempts {
			*quarantined++
			log.Printf("Warning: quarantining metrics outbox entry from %s after %d rejections: %v",
				group[idx].At, outboxMaxAttempts, cause)
			continue
		}
		log.Printf("Metrics outbox entry from %s rejected by hub (attempt %d/%d): %v",
			group[idx].At, group[idx].Attempts, outboxMaxAttempts, cause)
		survivors = append(survivors, group[idx])
	}
	return survivors
}

type outboxFailureClass int

const (
	// Transient: the hub is down, rate-limiting, or cannot authenticate the
	// node right now. Pause the flush and retry the same entries next cycle.
	outboxPause outboxFailureClass = iota
	// The hub received the request and rejected its contents; it will keep
	// rejecting this payload. Count an attempt and keep flushing past it.
	outboxPoison
)

// classifyOutboxFailure maps a push error to outboxPause/outboxPoison.
// Only HTTP-level content rejections (4xx) poison an entry: everything else
// — network errors, 5xx, and envelope-level scheduling responses such as
// "push interval not elapsed" or "raw push not required" — is retried
// later. The one exception is a metrics schema-version mismatch, which is
// permanent by definition: the node must upgrade, and queueing data behind
// a permanently rejected kind would only expose the outbox cap to silently
// dropping newer, deliverable data.
func classifyOutboxFailure(err error) outboxFailureClass {
	code := api.HTTPStatus(err)
	switch {
	case code == http.StatusTooManyRequests, code >= 500:
		return outboxPause
	case code == http.StatusUnauthorized, code == http.StatusForbidden, code == http.StatusNotFound:
		// Auth/identity problems affect every push equally; quarantining
		// while the node cannot authenticate at all would be pointless.
		return outboxPause
	case code >= 400:
		return outboxPoison
	default:
		// Envelope-level rejection (HTTP 200 with status != 0): a scheduling
		// decision, except for schema-version mismatches.
		var apiErr *api.APIError
		if errors.As(err, &apiErr) && strings.Contains(apiErr.Message, "schema version") {
			return outboxPoison
		}
		return outboxPause
	}
}

// isCorruptOutboxPayload reports whether the error came from decoding the
// entry's own payload (as opposed to the push itself). Such entries are
// undeliverable, carry no hub signal, and are dropped immediately.
func isCorruptOutboxPayload(err error) bool {
	var syntaxErr *json.SyntaxError
	var unmarshalErr *json.UnmarshalTypeError
	return errors.As(err, &syntaxErr) || errors.As(err, &unmarshalErr)
}

func applyMetaHashes(state *types.NodeState, metas []types.DeviceMetaEntry) {
	for _, m := range metas {
		if ds, ok := state.Devices[m.DeviceHash]; ok {
			ds.MetaHash = m.MetaHash
			state.Devices[m.DeviceHash] = ds
		}
	}
}

// filterUpdatedMetas keeps only the metas the hub reports as applied. An
// empty result list means the response predates per-item results; in that
// case the whole payload is treated as applied for backward compatibility.
func filterUpdatedMetas(
	metas []types.DeviceMetaEntry, results []types.MetaPushResult,
) []types.DeviceMetaEntry {
	if len(results) == 0 {
		return metas
	}
	updated := make(map[string]struct{}, len(results))
	for _, result := range results {
		if result.Updated {
			updated[result.DeviceHash] = struct{}{}
		}
	}
	applied := make([]types.DeviceMetaEntry, 0, len(metas))
	for _, m := range metas {
		if _, ok := updated[m.DeviceHash]; ok {
			applied = append(applied, m)
		}
	}
	return applied
}

// dropSupersededRaws removes queued snapshots for devices whose fresh
// snapshot was just accepted by the hub. Returns true when anything changed.
func dropSupersededRaws(state *types.NodeState, live map[int]types.RawEntry) bool {
	if len(live) == 0 {
		return false
	}
	kept := make([]types.OutboxEntry, 0, len(state.Outbox))
	changed := false
	for _, entry := range state.Outbox {
		if entry.Kind != types.OutboxKindRaws {
			kept = append(kept, entry)
			continue
		}
		var queued map[int]types.RawEntry
		if err := json.Unmarshal(entry.Payload, &queued); err != nil {
			kept = append(kept, entry)
			continue
		}
		for deviceID := range live {
			if _, superseded := queued[deviceID]; superseded {
				delete(queued, deviceID)
				changed = true
			}
		}
		if len(queued) == 0 {
			continue
		}
		payload, err := json.Marshal(queued)
		if err != nil {
			kept = append(kept, entry)
			continue
		}
		entry.Payload = payload
		kept = append(kept, entry)
	}
	if changed {
		state.Outbox = kept
	}
	return changed
}
