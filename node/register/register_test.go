package register

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"

	"github.com/unikii/dsentry/node/api"
	"github.com/unikii/dsentry/node/config"
	"github.com/unikii/dsentry/node/scanner"
	smartctl "github.com/unikii/dsentry/node/smartctl"
	"github.com/unikii/dsentry/node/types"
)

func TestRegisterDevicesPersistsNameWithoutMetrics(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(types.RegisterDevicesResponse{
			Status:  0,
			Payload: []types.RegisterDeviceResult{{DeviceHash: "hash", DeviceID: 4}},
		})
	}))
	defer server.Close()

	stateManager := config.NewStateManager(filepath.Join(t.TempDir(), "dsnode.json"))
	deviceMeta := &smartctl.DeviceMeta{
		DeviceName:  "/dev/disk0",
		ModelName:   "Mac SSD",
		Protocol:    "ata_ssd",
		SMARTStatus: 0,
	}
	device := scanner.ScannedDevice{
		DeviceName: "/dev/disk0",
		DeviceHash: "hash",
		MetaHash:   "meta",
		Meta:       deviceMeta,
	}

	client := &api.Client{BaseURL: server.URL, PushKey: "key", HTTP: server.Client()}
	if err := RegisterDevicesContext(context.Background(), client, stateManager, 1, []scanner.ScannedDevice{device}); err != nil {
		t.Fatal(err)
	}

	state, err := stateManager.Load()
	if err != nil {
		t.Fatal(err)
	}
	got := state.Devices["hash"]
	if got.DeviceName != "/dev/disk0" {
		t.Fatalf("device name = %q, want /dev/disk0", got.DeviceName)
	}
	if got.DeviceID != 4 {
		t.Fatalf("device id = %d, want 4", got.DeviceID)
	}
}

func TestNewFailingDeviceKeepsZeroBaseline(t *testing.T) {
	var requestBody []byte
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requestBody, _ = io.ReadAll(r.Body)
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(types.RegisterDevicesResponse{
			Status:  0,
			Payload: []types.RegisterDeviceResult{{DeviceHash: "failing", DeviceID: 9}},
		})
	}))
	defer server.Close()

	stateManager := config.NewStateManager(filepath.Join(t.TempDir(), "dsnode.json"))
	raw := []byte(`{"json_format_version":[1,0],"smartctl":{"version":[7,0],"exit_status":0},"device":{"name":"/dev/sda","type":"sat","protocol":"ATA"},"model_name":"FAILING DISK","serial_number":"SER-FAIL","user_capacity":{"bytes":1000204886016},"smart_status":{"passed":false},"temperature":{"current":33},"ata_smart_attributes":{"table":[{"id":5,"name":"Reallocated_Sector_Ct","value":100,"worst":100,"thresh":10,"raw":{"value":0,"string":"0"}}]}}`)
	device := scanner.ScannedDevice{
		DeviceName: "/dev/sda",
		DeviceHash: "failing",
		MetaHash:   "meta",
		RawOutput:  raw,
		Meta: &smartctl.DeviceMeta{
			DeviceName:           "/dev/sda",
			Protocol:             "ata",
			SMARTStatus:          1,
			SMARTThresholdStatus: 2,
		},
	}

	client := &api.Client{BaseURL: server.URL, PushKey: "key", HTTP: server.Client()}
	if err := RegisterDevicesContext(context.Background(), client, stateManager, 1, []scanner.ScannedDevice{device}); err != nil {
		t.Fatal(err)
	}

	state, err := stateManager.Load()
	if err != nil {
		t.Fatal(err)
	}
	got := state.Devices["failing"]
	if got.SmartStatus != 0 || got.ThresholdStatus != 0 {
		t.Fatalf("new failing device baseline = (%d,%d), want (0,0) so the first collection emits an alert",
			got.SmartStatus, got.ThresholdStatus)
	}

	// Registration carries identity/metadata/metrics only. Raw snapshots go
	// through the regular raw push so one scan is never stored twice.
	if strings.Contains(string(requestBody), "raw_brotli") {
		t.Fatal("registration request must not embed raw snapshots")
	}
}
