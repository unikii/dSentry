package types

import "encoding/json"

type DeviceState struct {
	DeviceID        int    `json:"device_id"`
	DeviceName      string `json:"device_name"`
	MetaHash        string `json:"meta_hash"`
	SmartStatus     int    `json:"smart_status"`
	ThresholdStatus int    `json:"threshold_status"`
	// Missing is true when the last scan no longer contained this device.
	// It suppresses duplicate "device_missing" events until it reappears.
	Missing bool `json:"missing,omitempty"`
}

type NodeState struct {
	ApiEndpoint string                 `json:"api_endpoint"`
	PushKey     string                 `json:"push_key"`
	NodeID      int                    `json:"node_id"`
	Devices     map[string]DeviceState `json:"devices"`
	Outbox      []OutboxEntry          `json:"outbox,omitempty"`
}

// OutboxEntry holds one hub push that could not be delivered (hub
// unreachable), persisted in the state file and flushed on reconnect.
// Kind selects the payload shape; see the OutboxKind* constants.
type OutboxEntry struct {
	Kind    string          `json:"kind"`
	At      string          `json:"at"`
	Payload json.RawMessage `json:"payload"`
	// Attempts counts consecutive hard (HTTP 4xx) rejections by the hub;
	// entries rejected this many times are quarantined so one poison
	// payload cannot wedge the queue. Transient failures never count.
	Attempts int `json:"attempts,omitempty"`
}

const (
	OutboxKindMetrics = "metrics"
	OutboxKindEvents  = "events"
	OutboxKindMetas   = "metas"
	OutboxKindRaws    = "raws"
)

type RegisterNodeRequest struct {
	PushKey  string `json:"push_key"`
	Hostname string `json:"hostname"`
	HostOS   string `json:"host_os"`
}

type RegisterNodeResponse struct {
	Status  int    `json:"status"`
	Message string `json:"message"`
	Payload struct {
		NodeID int `json:"node_id"`
	} `json:"payload"`
}

type DeviceRegistration struct {
	DeviceHash     string      `json:"device_hash"`
	MetaHash       string      `json:"meta_hash"`
	DeviceMeta     interface{} `json:"device_meta"`
	InitialMetrics interface{} `json:"initial_metrics,omitempty"`
}

type RegisterDevicesRequest struct {
	Devices []DeviceRegistration `json:"devices"`
}

type RegisterDeviceResult struct {
	DeviceHash string `json:"device_hash"`
	DeviceID   int    `json:"device_id"`
}

type RegisterDevicesResponse struct {
	Status  int                    `json:"status"`
	Message string                 `json:"message"`
	Payload []RegisterDeviceResult `json:"payload"`
}

type ConfigResponse struct {
	Status  int    `json:"status"`
	Message string `json:"message"`
	Payload struct {
		PushInterval    int     `json:"push_interval"`
		PushRaw         bool    `json:"push_raw"`
		PushRawPlain    bool    `json:"push_raw_plain"`
		LastMetricsPush *string `json:"last_metrics_push"`
		ServerTime      string  `json:"server_time"`
	} `json:"payload"`
}

const (
	StatusNodeNotRegistered  = 101
	StatusExceedsDeviceLimit = 201
	// StatusNoKnownDevices is a non-fatal hub response telling the node to
	// re-register its devices (e.g. after the hub database lost its device
	// rows). The node clears its local device ID map and registers again.
	StatusNoKnownDevices = 2
)

// MetricsSchemaVersion identifies the DeviceMetrics wire shape (see the
// DeviceMetrics doc comment in smartctl/parser.go). The hub rejects pushes
// stamped with a version it does not understand instead of mis-parsing them.
const MetricsSchemaVersion = 1

type MetricsPushRequest struct {
	SchemaVersion int           `json:"schema_version,omitempty"`
	Metrics       []interface{} `json:"metrics"`
}

type MetricsPushResponse struct {
	Status  int    `json:"status"`
	Message string `json:"message"`
}

type RawsPushResponse struct {
	Status  int    `json:"status"`
	Message string `json:"message"`
}

type RawEntry struct {
	Data []byte
	// CollectedAt is the UTC RFC3339 time the snapshot was taken. It is
	// sent in the multipart meta so queued raw snapshots keep their original
	// timestamp instead of being recorded at flush time.
	CollectedAt string `json:"collected_at,omitempty"`
}

type DeviceMetaEntry struct {
	DeviceHash string      `json:"device_hash"`
	MetaHash   string      `json:"meta_hash"`
	DeviceMeta interface{} `json:"device_meta,omitempty"`
}

type MetaPushRequest struct {
	Metas []DeviceMetaEntry `json:"metas"`
}

type MetaPushResponse struct {
	Status  int    `json:"status"`
	Message string `json:"message"`
	Payload struct {
		Results []MetaPushResult `json:"results"`
	} `json:"payload"`
}

// MetaPushResult reports whether the hub applied one meta update. Archived
// devices are skipped (updated=false) and must be retried after unarchive.
type MetaPushResult struct {
	DeviceHash string `json:"device_hash"`
	Updated    bool   `json:"updated"`
}

const (
	EventTypeSmartFail         = "device_smart_fail"
	EventTypeSmartSuccess      = "device_smart_success"
	EventTypeThresholdWarning  = "device_threshold_warning"
	EventTypeThresholdCritical = "device_threshold_critical"
	EventTypeDeviceMissing     = "device_missing"
	EventTypeDeviceOnline      = "device_online"
)

type DeviceEvent struct {
	DeviceHash string `json:"device_hash"`
	DeviceID   int    `json:"device_id"`
	EventType  string `json:"event_type"`
	// CollectedAt is the UTC RFC3339 time the event was detected. Queued
	// events keep this timestamp when the outbox is flushed later.
	CollectedAt string `json:"collected_at,omitempty"`
	Summary     string `json:"summary"`
	RawData     []byte `json:"raw_data,omitempty"`
}

type EventsPushResponse struct {
	Status  int    `json:"status"`
	Message string `json:"message"`
}
