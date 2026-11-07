package loop

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"log"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/unikii/dsentry/node/api"
	"github.com/unikii/dsentry/node/config"
	"github.com/unikii/dsentry/node/scanner"
	smartctl "github.com/unikii/dsentry/node/smartctl"
	"github.com/unikii/dsentry/node/types"
)

func writeFakeSmartctl(t *testing.T) string {
	t.Helper()
	script := filepath.Join(t.TempDir(), "fake-smartctl")
	content := `#!/bin/sh
for a in "$@"; do
  if [ "$a" = "--scan" ]; then
    printf '%s' '{"json_format_version":[1,0],"smartctl":{"version":[7,0]},"devices":[]}'
    exit 0
  fi
done
printf '%s' '{"json_format_version":[1,0],"smartctl":{"version":[7,0]},"devices":[]}'
`
	if err := os.WriteFile(script, []byte(content), 0755); err != nil {
		t.Fatal(err)
	}
	return script
}

func writeParseFailureSmartctl(t *testing.T) string {
	t.Helper()
	script := filepath.Join(t.TempDir(), "fake-smartctl")
	content := `#!/bin/sh
for a in "$@"; do
  if [ "$a" = "--scan" ]; then
    printf '%s' '{"json_format_version":[1,0],"smartctl":{"version":[7,4]},"devices":[{"name":"/dev/disk0","type":"ata","protocol":"ATA"}]}'
    exit 0
  fi
done
printf '%s' '{"json_format_version":[1,0],"smartctl":{"version":[7,4]},"device":{"name":"/dev/disk0","type":"ata","protocol":"ATA"},"model_name":"APPLE SSD TEST","serial_number":"TEST-SERIAL","smart_support":{"available":true,"enabled":true},"user_capacity":{"bytes":1000}}'
`
	if err := os.WriteFile(script, []byte(content), 0755); err != nil {
		t.Fatal(err)
	}
	return script
}

func TestWaitUntilWaitsForFutureDeadline(t *testing.T) {
	start := time.Now()
	if err := waitUntil(context.Background(), start.Add(50*time.Millisecond)); err != nil {
		t.Fatal(err)
	}
	if elapsed := time.Since(start); elapsed < 40*time.Millisecond {
		t.Fatalf("wait returned too early after %s", elapsed)
	}
}

func TestWaitUntilHonorsCancellation(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if err := waitUntil(ctx, time.Now().Add(time.Hour)); err != context.Canceled {
		t.Fatalf("wait error = %v, want context.Canceled", err)
	}
}

func TestWaitUntilDetectsWallClockJump(t *testing.T) {
	target := time.Now().Add(time.Hour)
	reads := []int64{
		time.Now().UnixNano(),
		time.Now().Add(2 * time.Hour).UnixNano(),
	}
	idx := 0
	err := waitUntilWithClock(context.Background(), target, func() int64 {
		if idx < len(reads) {
			v := reads[idx]
			idx++
			return v
		}
		return time.Now().UnixNano()
	})
	if err != nil {
		t.Fatal(err)
	}
}

func TestPushLoopDoesNotSpinWhenNotDue(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("shell helper unavailable on Windows")
	}

	oldLog := log.Writer()
	log.SetOutput(io.Discard)
	defer log.SetOutput(oldLog)

	var configPulls atomic.Int32
	now := time.Now().UTC().Format(time.RFC3339Nano)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		configPulls.Add(1)
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(types.ConfigResponse{
			Status: 0,
			Payload: struct {
				PushInterval    int     `json:"push_interval"`
				PushRaw         bool    `json:"push_raw"`
				PushRawPlain    bool    `json:"push_raw_plain"`
				LastMetricsPush *string `json:"last_metrics_push"`
				ServerTime      string  `json:"server_time"`
			}{PushInterval: 60, PushRaw: false, PushRawPlain: true, LastMetricsPush: &now, ServerTime: now},
		})
	}))
	defer server.Close()

	cfg := &config.Config{
		Commands: config.CommandsConfig{
			SmartctlBin:      writeFakeSmartctl(t),
			MetricsScanArgs:  "--scan --json",
			MetricsSmartArgs: "-x --json",
		},
	}
	statePath := filepath.Join(t.TempDir(), "dsnode.json")
	pl := New(
		api.NewClient(server.URL, "test-key", false),
		cfg,
		config.NewStateManager(statePath),
		scanner.New(cfg),
		1,
	)

	ctx, cancel := context.WithTimeout(context.Background(), 1200*time.Millisecond)
	defer cancel()
	pl.RunWithContext(ctx)

	if pulls := configPulls.Load(); pulls > 2 {
		t.Fatalf("config pulled %d times in ~1.2s while not due; loop is spinning", pulls)
	}
}

func TestPushLoopBacksOffWhenDueButNoMetrics(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("shell helper unavailable on Windows")
	}

	oldLog := log.Writer()
	log.SetOutput(io.Discard)
	defer log.SetOutput(oldLog)

	var configPulls atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		configPulls.Add(1)
		now := time.Now().UTC().Format(time.RFC3339Nano)
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"status":0,"payload":{"push_interval":60,"push_raw":false,"push_raw_plain":true,"last_metrics_push":null,"server_time":"` + now + `"}}`))
	}))
	defer server.Close()

	cfg := &config.Config{
		Commands: config.CommandsConfig{
			SmartctlBin:      writeFakeSmartctl(t),
			MetricsScanArgs:  "--scan --json",
			MetricsSmartArgs: "-x --json",
		},
	}
	pl := New(
		api.NewClient(server.URL, "test-key", false),
		cfg,
		config.NewStateManager(filepath.Join(t.TempDir(), "dsnode.json")),
		scanner.New(cfg),
		1,
	)

	ctx, cancel := context.WithTimeout(context.Background(), 1200*time.Millisecond)
	defer cancel()
	pl.RunWithContext(ctx)

	if pulls := configPulls.Load(); pulls > 2 {
		t.Fatalf("config pulled %d times in ~1.2s after a metric-less due cycle; loop is spinning", pulls)
	}
}

func TestPushLoopPushesRawWhenMetricsParseFails(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("shell helper unavailable on Windows")
	}

	oldLog := log.Writer()
	log.SetOutput(io.Discard)
	defer log.SetOutput(oldLog)

	var rawPushes atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.Method == http.MethodGet && strings.HasSuffix(r.URL.Path, "/configs"):
			now := time.Now().UTC().Format(time.RFC3339Nano)
			w.Header().Set("Content-Type", "application/json")
			_ = json.NewEncoder(w).Encode(types.ConfigResponse{
				Status: 0,
				Payload: struct {
					PushInterval    int     `json:"push_interval"`
					PushRaw         bool    `json:"push_raw"`
					PushRawPlain    bool    `json:"push_raw_plain"`
					LastMetricsPush *string `json:"last_metrics_push"`
					ServerTime      string  `json:"server_time"`
				}{PushInterval: 60, PushRaw: true, PushRawPlain: false, ServerTime: now},
			})
		case r.Method == http.MethodPost && strings.HasSuffix(r.URL.Path, "/raws"):
			if err := r.ParseMultipartForm(1 << 20); err != nil {
				http.Error(w, err.Error(), http.StatusBadRequest)
				return
			}
			if _, ok := r.MultipartForm.File["3"]; !ok {
				http.Error(w, "missing device raw part", http.StatusBadRequest)
				return
			}
			rawPushes.Add(1)
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write([]byte(`{"status":0,"message":""}`))
		default:
			http.Error(w, "not found", http.StatusNotFound)
		}
	}))
	defer server.Close()

	cfg := &config.Config{
		Commands: config.CommandsConfig{
			SmartctlBin:      writeParseFailureSmartctl(t),
			MetricsScanArgs:  "--scan --json",
			MetricsSmartArgs: "-x --json",
		},
	}
	output := &smartctl.SmartctlOutput{
		ModelName:    "APPLE SSD TEST",
		SerialNumber: "TEST-SERIAL",
	}
	deviceHash := smartctl.ComputeDeviceHash(output, "")
	stateManager := config.NewStateManager(filepath.Join(t.TempDir(), "dsnode.json"))
	if err := stateManager.Save(&types.NodeState{Devices: map[string]types.DeviceState{
		deviceHash: {DeviceID: 3, DeviceName: "disk0"},
	}}); err != nil {
		t.Fatal(err)
	}

	pl := New(api.NewClient(server.URL, "test-key", false), cfg, stateManager, scanner.New(cfg), 1)
	ctx, cancel := context.WithTimeout(context.Background(), 1200*time.Millisecond)
	defer cancel()
	pl.RunWithContext(ctx)

	if got := rawPushes.Load(); got != 1 {
		t.Fatalf("raw pushes = %d, want 1", got)
	}
}

func writeMetricsSmartctl(t *testing.T) string {
	t.Helper()
	script := filepath.Join(t.TempDir(), "fake-smartctl")
	content := `#!/bin/sh
for a in "$@"; do
  if [ "$a" = "--scan" ]; then
    printf '%s' '{"json_format_version":[1,0],"smartctl":{"version":[7,0]},"devices":[{"name":"/dev/sda","type":"sat","protocol":"ATA"}]}'
    exit 0
  fi
done
printf '%s' '{"json_format_version":[1,0],"smartctl":{"version":[7,0],"exit_status":0},"device":{"name":"/dev/sda","info_name":"/dev/sda [SAT]","type":"sat","protocol":"ATA"},"model_name":"TEST DISK","serial_number":"SER-OUTBOX","user_capacity":{"bytes":1000204886016},"smart_status":{"passed":true},"temperature":{"current":33},"ata_smart_attributes":{"table":[{"id":5,"name":"Reallocated_Sector_Ct","value":100,"worst":100,"thresh":10,"raw":{"value":0,"string":"0"}},{"id":194,"name":"Temperature_Celsius","value":67,"worst":55,"thresh":0,"raw":{"value":33,"string":"33"}}]}}'
`
	if err := os.WriteFile(script, []byte(content), 0755); err != nil {
		t.Fatal(err)
	}
	return script
}

// TestOfflineCycleQueuesAndFlushesMetrics: while the hub is down, collected
// metrics are persisted in the state outbox; when the hub returns, the
// backlog is flushed in a single batched POST with per-point timestamps.
func TestOfflineCycleQueuesAndFlushesMetrics(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("shell helper unavailable on Windows")
	}

	oldLog := log.Writer()
	log.SetOutput(io.Discard)
	defer log.SetOutput(oldLog)

	var configPulls atomic.Int32
	var metricsPushes atomic.Int32
	var mu sync.Mutex
	var metricBodies [][]byte

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		switch {
		case r.Method == http.MethodGet && strings.HasSuffix(r.URL.Path, "/configs"):
			if configPulls.Add(1) <= 2 {
				w.WriteHeader(http.StatusServiceUnavailable)
				_, _ = w.Write([]byte(`{"detail":"down"}`))
				return
			}
			now := time.Now().UTC().Format(time.RFC3339Nano)
			_, _ = w.Write([]byte(`{"status":0,"payload":{"push_interval":60,"push_raw":false,"push_raw_plain":true,"last_metrics_push":null,"server_time":"` + now + `"}}`))
		case r.Method == http.MethodPost && strings.HasSuffix(r.URL.Path, "/metrics"):
			body, _ := io.ReadAll(r.Body)
			mu.Lock()
			metricBodies = append(metricBodies, body)
			mu.Unlock()
			metricsPushes.Add(1)
			_, _ = w.Write([]byte(`{"status":0,"message":""}`))
		case r.Method == http.MethodPost && strings.HasSuffix(r.URL.Path, "/devices"):
			var req types.RegisterDevicesRequest
			_ = json.NewDecoder(r.Body).Decode(&req)
			results := make([]types.RegisterDeviceResult, 0, len(req.Devices))
			for _, d := range req.Devices {
				results = append(results, types.RegisterDeviceResult{DeviceHash: d.DeviceHash, DeviceID: 3})
			}
			_ = json.NewEncoder(w).Encode(types.RegisterDevicesResponse{Status: 0, Payload: results})
		default:
			http.Error(w, "not found", http.StatusNotFound)
		}
	}))
	defer server.Close()

	cfg := &config.Config{
		Commands: config.CommandsConfig{
			SmartctlBin:      writeMetricsSmartctl(t),
			MetricsScanArgs:  "--scan --json",
			MetricsSmartArgs: "-x --json",
		},
	}
	statePath := filepath.Join(t.TempDir(), "dsnode.json")
	pl := New(
		api.NewClient(server.URL, "test-key", false),
		cfg,
		config.NewStateManager(statePath),
		scanner.New(cfg),
		1,
	)
	pl.OfflineRetry = 60 * time.Millisecond
	pl.OfflineCadence = 60 * time.Millisecond

	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	if err := pl.RunWithContext(ctx); err != nil && !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("RunWithContext: %v", err)
	}

	if metricsPushes.Load() != 1 {
		t.Fatalf("metrics pushes = %d, want 1 (the batched backlog; the live point waits for the next interval)", metricsPushes.Load())
	}

	// The POST must carry the batched backlog with per-point times.
	mu.Lock()
	defer mu.Unlock()
	var backlog []map[string]interface{}
	for _, body := range metricBodies {
		var req struct {
			Metrics []map[string]interface{} `json:"metrics"`
		}
		if err := json.Unmarshal(body, &req); err != nil {
			t.Fatalf("bad metrics body: %v", err)
		}
		if len(req.Metrics) >= 2 {
			backlog = req.Metrics
		}
	}
	if len(backlog) < 2 {
		t.Fatalf("expected a batched flush with >=2 points, bodies: %s", metricBodies)
	}
	for _, point := range backlog {
		if _, ok := point["TimestampUTC"]; !ok {
			t.Fatalf("queued point missing TimestampUTC: %v", point)
		}
	}

	// The backlog and the live point share the single metrics POST, so the
	// outbox is drained completely.
	state, err := config.NewStateManager(statePath).Load()
	if err != nil {
		t.Fatal(err)
	}
	if len(state.Outbox) != 0 {
		t.Fatalf("outbox not drained: %+v", state.Outbox)
	}
}

// TestHotPlugRegistersNewDevice: a device that appears after startup is
// registered and its metrics pushed without a process restart.
func TestHotPlugRegistersNewDevice(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("shell helper unavailable on Windows")
	}

	oldLog := log.Writer()
	log.SetOutput(io.Discard)
	defer log.SetOutput(oldLog)

	var registrations atomic.Int32
	var metricsPushes atomic.Int32

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		switch {
		case r.Method == http.MethodGet && strings.HasSuffix(r.URL.Path, "/configs"):
			now := time.Now().UTC().Format(time.RFC3339Nano)
			_, _ = w.Write([]byte(`{"status":0,"payload":{"push_interval":60,"push_raw":false,"push_raw_plain":true,"last_metrics_push":null,"server_time":"` + now + `"}}`))
		case r.Method == http.MethodPost && strings.HasSuffix(r.URL.Path, "/metrics"):
			metricsPushes.Add(1)
			_, _ = w.Write([]byte(`{"status":0,"message":""}`))
		case r.Method == http.MethodPost && strings.HasSuffix(r.URL.Path, "/devices"):
			registrations.Add(1)
			var req types.RegisterDevicesRequest
			_ = json.NewDecoder(r.Body).Decode(&req)
			results := make([]types.RegisterDeviceResult, 0, len(req.Devices))
			for _, d := range req.Devices {
				results = append(results, types.RegisterDeviceResult{DeviceHash: d.DeviceHash, DeviceID: 7})
			}
			_ = json.NewEncoder(w).Encode(types.RegisterDevicesResponse{Status: 0, Payload: results})
		default:
			http.Error(w, "not found", http.StatusNotFound)
		}
	}))
	defer server.Close()

	cfg := &config.Config{
		Commands: config.CommandsConfig{
			SmartctlBin:      writeMetricsSmartctl(t),
			MetricsScanArgs:  "--scan --json",
			MetricsSmartArgs: "-x --json",
		},
	}
	statePath := filepath.Join(t.TempDir(), "dsnode.json")
	pl := New(
		api.NewClient(server.URL, "test-key", false),
		cfg,
		config.NewStateManager(statePath),
		scanner.New(cfg),
		1,
	)

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	if err := pl.RunWithContext(ctx); err != nil && !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("RunWithContext: %v", err)
	}

	if registrations.Load() == 0 {
		t.Fatal("hot-plugged device was never registered")
	}
	if metricsPushes.Load() == 0 {
		t.Fatal("metrics for the hot-plugged device were never pushed")
	}

	state, err := config.NewStateManager(statePath).Load()
	if err != nil {
		t.Fatal(err)
	}
	if len(state.Devices) != 1 {
		t.Fatalf("state devices = %d, want 1", len(state.Devices))
	}
	for _, ds := range state.Devices {
		if ds.DeviceID != 7 {
			t.Fatalf("device id = %d, want 7 (from registration response)", ds.DeviceID)
		}
	}
}

// TestRunWithContextReturnsFatalOnDeletedNode: an unregistered/deleted node
// error is returned wrapped in ErrFatal instead of killing the process
// from inside the loop.
func TestRunWithContextReturnsFatalOnDeletedNode(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("shell helper unavailable on Windows")
	}

	oldLog := log.Writer()
	log.SetOutput(io.Discard)
	defer log.SetOutput(oldLog)

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"status":101,"message":"Invalid push key"}`))
	}))
	defer server.Close()

	cfg := &config.Config{
		Commands: config.CommandsConfig{
			SmartctlBin:      writeFakeSmartctl(t),
			MetricsScanArgs:  "--scan --json",
			MetricsSmartArgs: "-x --json",
		},
	}
	pl := New(
		api.NewClient(server.URL, "test-key", false),
		cfg,
		config.NewStateManager(filepath.Join(t.TempDir(), "dsnode.json")),
		scanner.New(cfg),
		1,
	)

	err := pl.RunWithContext(context.Background())
	if !errors.Is(err, ErrFatal) {
		t.Fatalf("RunWithContext error = %v, want ErrFatal wrap", err)
	}
}

// TestFlushOutboxSkipsPoisonEntryAndQuarantines: a hub that hard-rejects
// (HTTP 400) one outbox entry must not wedge the entries behind it, and the
// poison entry is quarantined after outboxMaxAttempts rejections instead of
// blocking the queue forever.
func TestFlushOutboxSkipsPoisonEntryAndQuarantines(t *testing.T) {
	var eventsPushes atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		switch {
		case r.Method == http.MethodPost && strings.HasSuffix(r.URL.Path, "/events"):
			eventsPushes.Add(1)
			// Event pushes are multipart with an "events" form field.
			if err := r.ParseMultipartForm(1 << 20); err != nil {
				t.Errorf("bad multipart body: %v", err)
			}
			var events []types.DeviceEvent
			_ = json.Unmarshal([]byte(r.FormValue("events")), &events)
			for _, e := range events {
				if e.Summary == "poison" {
					w.WriteHeader(http.StatusBadRequest)
					_, _ = w.Write([]byte(`{"detail":"bad request"}`))
					return
				}
			}
			_, _ = w.Write([]byte(`{"status":0,"message":""}`))
		default:
			http.Error(w, "not found", http.StatusNotFound)
		}
	}))
	defer server.Close()

	statePath := filepath.Join(t.TempDir(), "dsnode.json")
	sm := config.NewStateManager(statePath)
	mkEvents := func(hash, summary string) []types.DeviceEvent {
		return []types.DeviceEvent{{DeviceHash: hash, EventType: types.EventTypeThresholdWarning, Summary: summary}}
	}
	state := &types.NodeState{
		ApiEndpoint: server.URL,
		NodeID:      1,
		Devices:     map[string]types.DeviceState{},
		Outbox: []types.OutboxEntry{
			{Kind: types.OutboxKindEvents, At: "t1", Payload: mustJSON(t, mkEvents("a", "ok"))},
			{Kind: types.OutboxKindEvents, At: "t2", Payload: mustJSON(t, mkEvents("b", "poison"))},
			{Kind: types.OutboxKindEvents, At: "t3", Payload: mustJSON(t, mkEvents("c", "ok"))},
		},
	}
	if err := sm.Save(state); err != nil {
		t.Fatal(err)
	}

	oldLog := log.Writer()
	log.SetOutput(io.Discard)
	defer log.SetOutput(oldLog)

	pl := New(
		api.NewClient(server.URL, "test-key", false),
		&config.Config{},
		sm,
		scanner.New(&config.Config{}),
		1,
	)

	ctx := context.Background()
	// First flush: the two good entries go out, the poison one is skipped.
	pl.flushOutbox(ctx, true, true)
	state, err := sm.Load()
	if err != nil {
		t.Fatal(err)
	}
	if len(state.Outbox) != 1 || state.Outbox[0].Attempts != 1 {
		t.Fatalf("after flush #1 outbox = %+v, want only the poison entry at attempt 1", state.Outbox)
	}

	// Keep flushing: the good entries behind the poison one must keep going
	// out, and the poison entry is quarantined on the outboxMaxAttempts-th.
	for attempt := 2; attempt <= outboxMaxAttempts; attempt++ {
		pl.flushOutbox(ctx, true, true)
		state, err = sm.Load()
		if err != nil {
			t.Fatal(err)
		}
		if attempt < outboxMaxAttempts {
			if len(state.Outbox) != 1 || state.Outbox[0].Attempts != attempt {
				t.Fatalf("after flush #%d outbox = %+v, want only the poison entry at attempt %d", attempt, state.Outbox, attempt)
			}
		} else if len(state.Outbox) != 0 {
			t.Fatalf("after flush #%d outbox = %+v, want the poison entry quarantined", attempt, state.Outbox)
		}
	}

	// Healthy entries never stopped flowing: 2 per flush for the first
	// flush (A and C behind it) — the poison entry's pushes are the only
	// extra ones (one per flush until quarantined).
	if eventsPushes.Load() < 2 {
		t.Fatalf("events pushes = %d, want the healthy entries delivered", eventsPushes.Load())
	}
}

// TestFlushOutboxPausesOnTransientFailure: network-level failures and
// envelope scheduling rejections pause the flush without counting
// quarantine attempts.
func TestFlushOutboxPausesOnTransientFailure(t *testing.T) {
	var eventsPushes atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		switch {
		case r.Method == http.MethodPost && strings.HasSuffix(r.URL.Path, "/events"):
			eventsPushes.Add(1)
			w.WriteHeader(http.StatusServiceUnavailable)
			_, _ = w.Write([]byte(`{"detail":"down"}`))
		default:
			http.Error(w, "not found", http.StatusNotFound)
		}
	}))
	defer server.Close()

	statePath := filepath.Join(t.TempDir(), "dsnode.json")
	sm := config.NewStateManager(statePath)
	state := &types.NodeState{
		ApiEndpoint: server.URL,
		NodeID:      1,
		Devices:     map[string]types.DeviceState{},
		Outbox: []types.OutboxEntry{
			{Kind: types.OutboxKindEvents, At: "t1", Payload: mustJSON(t, []types.DeviceEvent{{DeviceHash: "a", EventType: types.EventTypeThresholdWarning}})},
			{Kind: types.OutboxKindEvents, At: "t2", Payload: mustJSON(t, []types.DeviceEvent{{DeviceHash: "b", EventType: types.EventTypeThresholdWarning}})},
		},
	}
	if err := sm.Save(state); err != nil {
		t.Fatal(err)
	}

	oldLog := log.Writer()
	log.SetOutput(io.Discard)
	defer log.SetOutput(oldLog)

	pl := New(
		api.NewClient(server.URL, "test-key", false),
		&config.Config{},
		sm,
		scanner.New(&config.Config{}),
		1,
	)

	pl.flushOutbox(context.Background(), true, true)
	state, err := sm.Load()
	if err != nil {
		t.Fatal(err)
	}
	// The flush stops at the first transient failure: the second entry is
	// never even attempted, and no attempts were counted.
	if len(state.Outbox) != 2 {
		t.Fatalf("outbox after paused flush = %+v, want both entries kept", state.Outbox)
	}
	for _, e := range state.Outbox {
		if e.Attempts != 0 {
			t.Fatalf("entry %s counted attempts on a transient failure: %+v", e.At, e)
		}
	}
}

// TestClassifyOutboxFailure pins the pause-vs-poison decisions.
func TestClassifyOutboxFailure(t *testing.T) {
	cases := []struct {
		name string
		err  error
		want outboxFailureClass
	}{
		{"network error", errors.New("dial tcp: connection refused"), outboxPause},
		{"server error", &api.HTTPError{StatusCode: 500, Body: "boom"}, outboxPause},
		{"rate limited", &api.HTTPError{StatusCode: 429, Body: "slow down"}, outboxPause},
		{"unauthorized", &api.HTTPError{StatusCode: 401, Body: "no"}, outboxPause},
		{"forbidden", &api.HTTPError{StatusCode: 403, Body: "disabled"}, outboxPause},
		{"not found", &api.HTTPError{StatusCode: 404, Body: "gone"}, outboxPause},
		{"bad request", &api.HTTPError{StatusCode: 400, Body: "bad"}, outboxPoison},
		{"payload too large", &api.HTTPError{StatusCode: 413, Body: "big"}, outboxPoison},
		{"unprocessible", &api.HTTPError{StatusCode: 422, Body: "nope"}, outboxPoison},
		{"interval enforcement", &api.APIError{Operation: "push metrics", Status: 1, Message: "Push interval not elapsed"}, outboxPause},
		{"raws not required", &api.APIError{Operation: "push raws", Status: 1, Message: "Raw push not required at this time"}, outboxPause},
		{"schema version mismatch", &api.APIError{Operation: "push metrics", Status: 1, Message: "Unsupported metrics schema version: 99"}, outboxPoison},
		{"node not found", &api.APIError{Operation: "push metrics", Status: 101, Message: "Node not found"}, outboxPause},
	}
	for _, tc := range cases {
		if got := classifyOutboxFailure(tc.err); got != tc.want {
			t.Errorf("%s: classifyOutboxFailure = %v, want %v", tc.name, got, tc.want)
		}
	}
}

func mustJSON(t *testing.T, v interface{}) json.RawMessage {
	t.Helper()
	data, err := json.Marshal(v)
	if err != nil {
		t.Fatal(err)
	}
	return data
}

func TestFlushOutboxSendsOneMetricsBatchPerInterval(t *testing.T) {
	var metricsPushes atomic.Int32
	var eventPushes atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		switch {
		case strings.HasSuffix(r.URL.Path, "/metrics"):
			metricsPushes.Add(1)
			_, _ = w.Write([]byte(`{"status":0,"message":""}`))
		case strings.HasSuffix(r.URL.Path, "/events"):
			eventPushes.Add(1)
			_, _ = w.Write([]byte(`{"status":0,"message":""}`))
		default:
			http.NotFound(w, r)
		}
	}))
	defer server.Close()

	oldLog := log.Writer()
	log.SetOutput(io.Discard)
	defer log.SetOutput(oldLog)

	makePoints := func(hash string) []interface{} {
		points := make([]interface{}, maxReplayMetricsPoints/2+100)
		for i := range points {
			points[i] = map[string]interface{}{"DeviceHash": hash, "TemperatureCelsius": i}
		}
		return points
	}

	sm := config.NewStateManager(filepath.Join(t.TempDir(), "state.json"))
	state := &types.NodeState{
		ApiEndpoint: server.URL,
		NodeID:      1,
		Devices:     map[string]types.DeviceState{},
		Outbox: []types.OutboxEntry{
			{Kind: types.OutboxKindMetrics, At: "m1", Payload: mustJSON(t, makePoints("a"))},
			{Kind: types.OutboxKindMetrics, At: "m2", Payload: mustJSON(t, makePoints("b"))},
			{Kind: types.OutboxKindEvents, At: "e1", Payload: mustJSON(t, []types.DeviceEvent{{DeviceHash: "a", EventType: types.EventTypeSmartFail}})},
		},
	}
	if err := sm.Save(state); err != nil {
		t.Fatal(err)
	}

	pl := New(api.NewClient(server.URL, "test-key", false), &config.Config{}, sm, scanner.New(&config.Config{}), 1)

	// Non-metrics flush must leave both metrics entries alone, but still
	// deliver the event.
	if sent := pl.flushOutbox(context.Background(), false, true); sent {
		t.Fatal("non-metrics flush reported a metrics delivery")
	}
	if got := metricsPushes.Load(); got != 0 {
		t.Fatalf("metrics pushes with includeMetrics=false = %d, want 0", got)
	}
	if got := eventPushes.Load(); got != 1 {
		t.Fatalf("event pushes = %d, want 1", got)
	}
	state, err := sm.Load()
	if err != nil {
		t.Fatal(err)
	}
	if len(state.Outbox) != 2 {
		t.Fatalf("outbox after non-metrics flush = %+v, want 2 metrics entries", state.Outbox)
	}

	// Each interval flushes exactly one metrics batch.
	if sent := pl.flushOutbox(context.Background(), true, true); !sent {
		t.Fatal("metrics flush did not report its delivery")
	}
	if got := metricsPushes.Load(); got != 1 {
		t.Fatalf("metrics pushes after first interval = %d, want 1", got)
	}
	state, err = sm.Load()
	if err != nil {
		t.Fatal(err)
	}
	if len(state.Outbox) != 1 {
		t.Fatalf("outbox after first interval = %+v, want 1 entry", state.Outbox)
	}

	if sent := pl.flushOutbox(context.Background(), true, true); !sent {
		t.Fatal("second metrics flush did not report its delivery")
	}
	if got := metricsPushes.Load(); got != 2 {
		t.Fatalf("metrics pushes after second interval = %d, want 2", got)
	}
	state, err = sm.Load()
	if err != nil {
		t.Fatal(err)
	}
	if len(state.Outbox) != 0 {
		t.Fatalf("outbox after second interval = %+v, want empty", state.Outbox)
	}
}

func TestDeliverMergesLiveMetricsWithBacklog(t *testing.T) {
	var metricsPushes atomic.Int32
	var body []byte
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		metricsPushes.Add(1)
		body, _ = io.ReadAll(r.Body)
		_, _ = w.Write([]byte(`{"status":0,"message":""}`))
	}))
	defer server.Close()

	oldLog := log.Writer()
	log.SetOutput(io.Discard)
	defer log.SetOutput(oldLog)

	sm := config.NewStateManager(filepath.Join(t.TempDir(), "state.json"))
	state := &types.NodeState{
		ApiEndpoint: server.URL,
		NodeID:      1,
		Devices:     map[string]types.DeviceState{},
		Outbox: []types.OutboxEntry{{
			Kind:    types.OutboxKindMetrics,
			At:      "m1",
			Payload: mustJSON(t, []interface{}{map[string]interface{}{"DeviceHash": "a"}}),
		}},
	}
	if err := sm.Save(state); err != nil {
		t.Fatal(err)
	}

	pl := New(api.NewClient(server.URL, "test-key", false), &config.Config{}, sm, scanner.New(&config.Config{}), 1)
	data := &cycleData{
		state:   state,
		metrics: []interface{}{map[string]interface{}{"DeviceHash": "a", "TemperatureCelsius": 30}},
	}
	pl.deliver(context.Background(), data)

	if got := metricsPushes.Load(); got != 1 {
		t.Fatalf("metrics pushes = %d, want one merged push", got)
	}
	var req struct {
		Metrics []map[string]interface{} `json:"metrics"`
	}
	if err := json.Unmarshal(body, &req); err != nil {
		t.Fatal(err)
	}
	if len(req.Metrics) != 2 {
		t.Fatalf("merged metrics points = %d, want 2: %s", len(req.Metrics), body)
	}
	saved, err := sm.Load()
	if err != nil {
		t.Fatal(err)
	}
	if len(saved.Outbox) != 0 {
		t.Fatalf("outbox = %+v, want drained after the merged push", saved.Outbox)
	}
}

func TestCollectContinuesWhenNewDeviceRegistrationFails(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("shell helper unavailable on Windows")
	}

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		if strings.HasSuffix(r.URL.Path, "/devices") {
			http.Error(w, "hub down", http.StatusServiceUnavailable)
			return
		}
		http.NotFound(w, r)
	}))
	defer server.Close()

	oldLog := log.Writer()
	log.SetOutput(io.Discard)
	defer log.SetOutput(oldLog)

	cfg := &config.Config{Commands: config.CommandsConfig{
		SmartctlBin:      writeMetricsSmartctl(t),
		MetricsScanArgs:  "--scan --json",
		MetricsSmartArgs: "-x --json",
	}}
	sm := config.NewStateManager(filepath.Join(t.TempDir(), "state.json"))
	pl := New(api.NewClient(server.URL, "test-key", false), cfg, sm, scanner.New(cfg), 1)

	data, err := pl.collect(context.Background(), collectOptions{})
	if err != nil {
		t.Fatalf("collect returned error when only new-device registration failed: %v", err)
	}
	if data == nil {
		t.Fatal("collect returned nil data")
	}
}

func writeFailingSmartctl(t *testing.T) string {
	t.Helper()
	script := filepath.Join(t.TempDir(), "fake-smartctl")
	content := `#!/bin/sh
for a in "$@"; do
  if [ "$a" = "--scan" ]; then
    printf '%s' '{"json_format_version":[1,0],"smartctl":{"version":[7,0]},"devices":[{"name":"/dev/sda","type":"sat","protocol":"ATA"}]}'
    exit 0
  fi
done
printf '%s' '{"json_format_version":[1,0],"smartctl":{"version":[7,0],"exit_status":0},"device":{"name":"/dev/sda","info_name":"/dev/sda [SAT]","type":"sat","protocol":"ATA"},"model_name":"FAILING DISK","serial_number":"SER-FAIL","user_capacity":{"bytes":1000204886016},"smart_status":{"passed":false},"temperature":{"current":33},"ata_smart_attributes":{"table":[{"id":5,"name":"Reallocated_Sector_Ct","value":100,"worst":100,"thresh":10,"raw":{"value":0,"string":"0"}}]}}'
`
	if err := os.WriteFile(script, []byte(content), 0755); err != nil {
		t.Fatal(err)
	}
	return script
}

func TestFirstCollectionEmitsEventForInitiallyFailingDisk(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("shell helper unavailable on Windows")
	}

	oldLog := log.Writer()
	log.SetOutput(io.Discard)
	defer log.SetOutput(oldLog)

	cfg := &config.Config{Commands: config.CommandsConfig{
		SmartctlBin:      writeFailingSmartctl(t),
		MetricsScanArgs:  "--scan --json",
		MetricsSmartArgs: "-x --json",
	}}
	sm := config.NewStateManager(filepath.Join(t.TempDir(), "state.json"))
	pl := New(api.NewClient("http://127.0.0.1:1", "test-key", false), cfg, sm, scanner.New(cfg), 1)

	scanned, err := pl.scanAndPopulate(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if len(scanned) != 1 {
		t.Fatalf("scanned devices = %d, want 1", len(scanned))
	}
	if err := sm.Save(&types.NodeState{
		Devices: map[string]types.DeviceState{
			scanned[0].DeviceHash: {
				DeviceID:   1,
				DeviceName: scanned[0].DeviceName,
				// Registration intentionally leaves a new disk at this
				// baseline so the first collection detects the failure.
				SmartStatus:     0,
				ThresholdStatus: 0,
			},
		},
	}); err != nil {
		t.Fatal(err)
	}

	data, err := pl.collect(context.Background(), collectOptions{})
	if err != nil {
		t.Fatal(err)
	}
	found := false
	for _, event := range data.events {
		if event.EventType == types.EventTypeSmartFail {
			found = true
		}
	}
	if !found {
		t.Fatalf("events = %+v, want an initial smart-fail event", data.events)
	}
}

func writeFailingNoAttrsSmartctl(t *testing.T) string {
	t.Helper()
	script := filepath.Join(t.TempDir(), "fake-smartctl")
	content := `#!/bin/sh
for a in "$@"; do
  if [ "$a" = "--scan" ]; then
    printf '%s' '{"json_format_version":[1,0],"smartctl":{"version":[7,0]},"devices":[{"name":"/dev/sda","type":"sat","protocol":"ATA"}]}'
    exit 0
  fi
done
printf '%s' '{"json_format_version":[1,0],"smartctl":{"version":[7,0],"exit_status":0},"device":{"name":"/dev/sda","info_name":"/dev/sda [SAT]","type":"sat","protocol":"ATA"},"model_name":"DEGRADED DISK","serial_number":"SER-DEGRADED","user_capacity":{"bytes":1000204886016},"smart_status":{"passed":false}}'
`
	if err := os.WriteFile(script, []byte(content), 0755); err != nil {
		t.Fatal(err)
	}
	return script
}

// TestCollectEmitsStatusEventWithoutMetrics: smart_status.failed must produce
// an event even when the attribute/health log cannot be parsed.
func TestCollectEmitsStatusEventWithoutMetrics(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("shell helper unavailable on Windows")
	}

	oldLog := log.Writer()
	log.SetOutput(io.Discard)
	defer log.SetOutput(oldLog)

	cfg := &config.Config{Commands: config.CommandsConfig{
		SmartctlBin:      writeFailingNoAttrsSmartctl(t),
		MetricsScanArgs:  "--scan --json",
		MetricsSmartArgs: "-x --json",
	}}
	sm := config.NewStateManager(filepath.Join(t.TempDir(), "state.json"))
	pl := New(api.NewClient("http://127.0.0.1:1", "test-key", false), cfg, sm, scanner.New(cfg), 1)

	scanned, err := pl.scanAndPopulate(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if len(scanned) != 1 {
		t.Fatalf("scanned devices = %d, want 1", len(scanned))
	}
	if err := sm.Save(&types.NodeState{Devices: map[string]types.DeviceState{
		scanned[0].DeviceHash: {DeviceID: 1, DeviceName: scanned[0].DeviceName},
	}}); err != nil {
		t.Fatal(err)
	}

	data, err := pl.collect(context.Background(), collectOptions{})
	if err != nil {
		t.Fatal(err)
	}
	if len(data.metrics) != 0 {
		t.Fatalf("metrics = %d, want none for unparseable attributes", len(data.metrics))
	}
	found := false
	for _, event := range data.events {
		if event.EventType == types.EventTypeSmartFail {
			found = true
		}
	}
	if !found {
		t.Fatalf("events = %+v, want a smart-fail event despite metrics failure", data.events)
	}
}

// TestCollectEmitsDeviceMissingEventOnce: a device absent from the scan emits
// one device_missing event, not one per cycle.
func TestCollectEmitsDeviceMissingEventOnce(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("shell helper unavailable on Windows")
	}

	oldLog := log.Writer()
	log.SetOutput(io.Discard)
	defer log.SetOutput(oldLog)

	cfg := &config.Config{Commands: config.CommandsConfig{
		SmartctlBin:      writeFakeSmartctl(t),
		MetricsScanArgs:  "--scan --json",
		MetricsSmartArgs: "-x --json",
	}}
	statePath := filepath.Join(t.TempDir(), "state.json")
	sm := config.NewStateManager(statePath)
	if err := sm.Save(&types.NodeState{Devices: map[string]types.DeviceState{
		"missing-hash": {DeviceID: 4, DeviceName: "/dev/gone"},
	}}); err != nil {
		t.Fatal(err)
	}
	pl := New(api.NewClient("http://127.0.0.1:1", "test-key", false), cfg, sm, scanner.New(cfg), 1)

	first, err := pl.collect(context.Background(), collectOptions{})
	if err != nil {
		t.Fatal(err)
	}
	countMissing := func(events []types.DeviceEvent) int {
		n := 0
		for _, e := range events {
			if e.EventType == types.EventTypeDeviceMissing {
				n++
			}
		}
		return n
	}
	if got := countMissing(first.events); got != 1 {
		t.Fatalf("first cycle missing events = %d, want 1", got)
	}
	pl.deliverOffline(first)

	second, err := pl.collect(context.Background(), collectOptions{})
	if err != nil {
		t.Fatal(err)
	}
	if got := countMissing(second.events); got != 0 {
		t.Fatalf("second cycle missing events = %d, want 0", got)
	}
}

// TestDuePreFlushLeavesRawsForLiveCycle pins the raw-outbox ordering fix.
func TestDuePreFlushLeavesRawsForLiveCycle(t *testing.T) {
	var rawPushes atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.HasSuffix(r.URL.Path, "/raws") {
			rawPushes.Add(1)
		}
		_, _ = w.Write([]byte(`{"status":0,"message":""}`))
	}))
	defer server.Close()

	oldLog := log.Writer()
	log.SetOutput(io.Discard)
	defer log.SetOutput(oldLog)

	sm := config.NewStateManager(filepath.Join(t.TempDir(), "state.json"))
	state := &types.NodeState{
		NodeID:  1,
		Devices: map[string]types.DeviceState{},
		Outbox: []types.OutboxEntry{{
			Kind:    types.OutboxKindRaws,
			At:      "r1",
			Payload: mustJSON(t, map[int]types.RawEntry{3: {Data: []byte("old")}}),
		}},
	}
	if err := sm.Save(state); err != nil {
		t.Fatal(err)
	}
	pl := New(api.NewClient(server.URL, "test-key", false), &config.Config{}, sm, scanner.New(&config.Config{}), 1)

	if pl.flushOutbox(context.Background(), false, false) {
		t.Fatal("pre-cycle flush reported a delivery")
	}
	if rawPushes.Load() != 0 {
		t.Fatalf("raw pushes before live cycle = %d, want 0", rawPushes.Load())
	}
	if pl.flushOutbox(context.Background(), false, true) != false {
		// flushOutbox returns whether metrics were flushed, not raws.
	}
	if rawPushes.Load() != 1 {
		t.Fatalf("raw pushes = %d, want 1 once raws are allowed", rawPushes.Load())
	}
}

// TestDeliverDropsSupersededQueuedRaws: a successful live raw push removes
// older queued snapshots so they cannot consume the next raw slot.
func TestDeliverDropsSupersededQueuedRaws(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte(`{"status":0,"message":""}`))
	}))
	defer server.Close()

	oldLog := log.Writer()
	log.SetOutput(io.Discard)
	defer log.SetOutput(oldLog)

	sm := config.NewStateManager(filepath.Join(t.TempDir(), "state.json"))
	if err := sm.Save(&types.NodeState{
		NodeID:  1,
		Devices: map[string]types.DeviceState{},
		Outbox: []types.OutboxEntry{{
			Kind:    types.OutboxKindRaws,
			At:      "r1",
			Payload: mustJSON(t, map[int]types.RawEntry{3: {Data: []byte("old")}, 4: {Data: []byte("other")}}),
		}},
	}); err != nil {
		t.Fatal(err)
	}
	state, _ := sm.Load()
	pl := New(api.NewClient(server.URL, "test-key", false), &config.Config{}, sm, scanner.New(&config.Config{}), 1)
	pl.deliver(context.Background(), &cycleData{
		state: state,
		raws:  map[int]types.RawEntry{3: {Data: []byte("new")}},
	})

	saved, err := sm.Load()
	if err != nil {
		t.Fatal(err)
	}
	if len(saved.Outbox) != 1 {
		t.Fatalf("outbox = %+v, want one entry for the non-superseded device", saved.Outbox)
	}
	var remaining map[int]types.RawEntry
	if err := json.Unmarshal(saved.Outbox[0].Payload, &remaining); err != nil {
		t.Fatal(err)
	}
	if _, ok := remaining[4]; !ok || len(remaining) != 1 {
		t.Fatalf("remaining raws = %+v, want only device 4", remaining)
	}
}

// TestEnqueueOutboxDedupesMetas: repeated offline collections keep one queued
// meta per device hash.
func TestEnqueueOutboxDedupesMetas(t *testing.T) {
	sm := config.NewStateManager(filepath.Join(t.TempDir(), "state.json"))
	state := &types.NodeState{Devices: map[string]types.DeviceState{}}
	pl := New(nil, &config.Config{}, sm, scanner.New(&config.Config{}), 1)

	pl.enqueueOutbox(state, types.OutboxKindMetas, []types.DeviceMetaEntry{{DeviceHash: "a", MetaHash: "1"}})
	pl.enqueueOutbox(state, types.OutboxKindMetas, []types.DeviceMetaEntry{{DeviceHash: "b", MetaHash: "1"}})
	pl.enqueueOutbox(state, types.OutboxKindMetas, []types.DeviceMetaEntry{{DeviceHash: "a", MetaHash: "2"}})

	if len(state.Outbox) != 1 {
		t.Fatalf("outbox entries = %d, want 1 deduped meta entry", len(state.Outbox))
	}
	var metas []types.DeviceMetaEntry
	if err := json.Unmarshal(state.Outbox[0].Payload, &metas); err != nil {
		t.Fatal(err)
	}
	if len(metas) != 2 {
		t.Fatalf("queued metas = %d, want 2 distinct hashes: %+v", len(metas), metas)
	}
	for _, m := range metas {
		if m.DeviceHash == "a" && m.MetaHash != "2" {
			t.Fatalf("hash a = %q, want the newest payload", m.MetaHash)
		}
	}
}

// TestDeliverAppliesOnlyUpdatedMetaHashes: archived/unknown metas (updated =
// false) must not advance the local hash.
func TestDeliverAppliesOnlyUpdatedMetaHashes(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"status":0,"payload":{"results":[{"device_hash":"a","updated":false},{"device_hash":"b","updated":true}]}}`))
	}))
	defer server.Close()

	oldLog := log.Writer()
	log.SetOutput(io.Discard)
	defer log.SetOutput(oldLog)

	sm := config.NewStateManager(filepath.Join(t.TempDir(), "state.json"))
	if err := sm.Save(&types.NodeState{NodeID: 1, Devices: map[string]types.DeviceState{
		"a": {DeviceID: 1, MetaHash: "old-a"},
		"b": {DeviceID: 2, MetaHash: "old-b"},
	}}); err != nil {
		t.Fatal(err)
	}
	state, _ := sm.Load()
	pl := New(api.NewClient(server.URL, "test-key", false), &config.Config{}, sm, scanner.New(&config.Config{}), 1)
	pl.deliver(context.Background(), &cycleData{
		state: state,
		metas: []types.DeviceMetaEntry{
			{DeviceHash: "a", MetaHash: "new-a"},
			{DeviceHash: "b", MetaHash: "new-b"},
		},
	})

	saved, err := sm.Load()
	if err != nil {
		t.Fatal(err)
	}
	if saved.Devices["a"].MetaHash != "old-a" {
		t.Fatalf("archived meta hash advanced to %q", saved.Devices["a"].MetaHash)
	}
	if saved.Devices["b"].MetaHash != "new-b" {
		t.Fatalf("updated meta hash = %q, want new-b", saved.Devices["b"].MetaHash)
	}
}

// TestDeliverClearsDeviceIDsWhenHubKnowsNoDevices: status 2 tells the node to
// re-register its devices instead of pushing into the void forever.
func TestDeliverClearsDeviceIDsWhenHubKnowsNoDevices(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"status":2,"message":"No known devices"}`))
	}))
	defer server.Close()

	oldLog := log.Writer()
	log.SetOutput(io.Discard)
	defer log.SetOutput(oldLog)

	sm := config.NewStateManager(filepath.Join(t.TempDir(), "state.json"))
	if err := sm.Save(&types.NodeState{NodeID: 1, Devices: map[string]types.DeviceState{
		"stale-hash": {DeviceID: 9, DeviceName: "/dev/sda"},
	}}); err != nil {
		t.Fatal(err)
	}
	state, _ := sm.Load()
	pl := New(api.NewClient(server.URL, "test-key", false), &config.Config{}, sm, scanner.New(&config.Config{}), 1)
	pl.deliver(context.Background(), &cycleData{
		state:   state,
		metrics: []interface{}{map[string]interface{}{"DeviceHash": "stale-hash"}},
	})

	saved, err := sm.Load()
	if err != nil {
		t.Fatal(err)
	}
	if len(saved.Devices) != 0 {
		t.Fatalf("devices = %+v, want cleared for re-registration", saved.Devices)
	}
	if len(saved.Outbox) == 0 || saved.Outbox[0].Kind != types.OutboxKindMetrics {
		t.Fatalf("outbox = %+v, want the live metrics queued for replay", saved.Outbox)
	}
}
