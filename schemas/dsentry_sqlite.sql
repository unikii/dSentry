-- ================================================
-- dSentry SQLite Schema
-- Relational data: users, nodes, devices,
--   device_raw, events, user_alert
-- ================================================

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE,
    password_hash TEXT,
    oauth_provider TEXT,
    oauth_id TEXT,
    node_limit INTEGER,
    node_device_limit INTEGER,
    status INTEGER NOT NULL DEFAULT 0,
    reg_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(oauth_provider, oauth_id)
);

CREATE TABLE IF NOT EXISTS node (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    hostname TEXT,
    host_os TEXT,
    push_key TEXT UNIQUE NOT NULL,
    push_count INTEGER DEFAULT 0,
    tags TEXT,                      -- JSON array of strings, e.g. '["prod","home"]'
    last_raw_push TEXT,
    last_metrics_push TEXT,
    last_device_push TEXT,          -- JSON array of device ids, e.g. "[1,2,3]"
    reg_at TEXT DEFAULT NULL,
    add_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS device (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    device_type TEXT NOT NULL,      -- nvme | ata_hdd | ata_ssd | scsi_hdd | scsi_ssd
    using_protocol TEXT,
    device_ext TEXT,                -- JSON object, structure varies by device_type
    device_hash TEXT NOT NULL,
    meta_hash TEXT NOT NULL,
    device_name TEXT,
    smart_status INTEGER,           -- 0=PASSED, 1=FAILED
    threshold_status INTEGER DEFAULT 0, -- 0=PASSED, 1=WARNING, 2=FAILED
    last_event_at TEXT,             -- datetime of most recent event
    smart_enabled INTEGER,          -- 0/1
    smart_available INTEGER,        -- 0/1
    tags TEXT,                      -- JSON array of strings, e.g. '["prod","db"]'
    serial_number TEXT NOT NULL,
    model_name TEXT NOT NULL,
    vendor TEXT,
    total_capacity_bytes INTEGER NOT NULL,
    firmware_version TEXT,
    archived INTEGER NOT NULL DEFAULT 0,
    reg_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(device_hash, user_id)
);

/*
device_ext JSON structure per device_type:

nvme: {
    pci_vendor_id, pci_vendor_subsystem_id, ieee_oui_identifier,
    available_spare_threshold, warn_comp_temp_threshold,
    critical_comp_temp_threshold, maximum_data_transfer_size
}
ata_ssd: {
    wwn, ssd_tbw_warranty,
    min_temperature_celsius, max_temperature_celsius
}
ata_hdd: {
    wwn, form_factor, rotation_rate,
    min_temperature_celsius, max_temperature_celsius
}
scsi_ssd: {
    logical_unit_id, manufacturing_date, drive_trip_temperature,
    ssd_tbw_warranty
}
scsi_hdd: {
    logical_unit_id, manufacturing_date, drive_trip_temperature,
    hdd_specified_cycle_count, hdd_specified_load_unload_count
}
*/

CREATE TABLE IF NOT EXISTS device_raw (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id INTEGER NOT NULL REFERENCES device(id),
    raw_output BLOB NOT NULL,       -- brotli-compressed JSON + optional plain text
    add_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    event_type TEXT NOT NULL,       -- device_smart_fail | device_smart_success |
                                    -- device_threshold_warning | device_threshold_critical
    device_id INTEGER REFERENCES device(id) ON DELETE SET NULL,
    note TEXT,
    alert_at TEXT DEFAULT NULL,
    act_at TEXT DEFAULT NULL,
    add_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Durable alert-delivery queue. A row is created in the same transaction as
-- the event, so a crash or notification outage does not lose the alert.
CREATE TABLE IF NOT EXISTS event_alert_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL UNIQUE REFERENCES events(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id),
    event_type TEXT NOT NULL,
    device_id INTEGER,
    note TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    next_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_error TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,            -- JWT jti (session id)
    user_id INTEGER NOT NULL REFERENCES users(id),
    expires_at TEXT NOT NULL,
    revoked_at TEXT DEFAULT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS user_alert (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    alert_name TEXT,
    alert_type TEXT NOT NULL,      -- email | discord | telegram | ... (Apprise services)
    alert_target TEXT NOT NULL,    -- URL or Email or phone number or other target
    enabled INTEGER DEFAULT 0,
    edit_at TEXT DEFAULT NULL,
    add_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ========== INDEXES ==========
CREATE INDEX IF NOT EXISTS idx_node_user_id ON node(user_id);
CREATE INDEX IF NOT EXISTS idx_device_user_archived ON device(user_id, archived);
CREATE INDEX IF NOT EXISTS idx_device_hash ON device(device_hash);
CREATE INDEX IF NOT EXISTS idx_device_raw_device_addat ON device_raw(device_id, add_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_user_addat ON events(user_id, add_at DESC);
CREATE INDEX IF NOT EXISTS idx_event_alert_queue_due ON event_alert_queue(next_at);
CREATE INDEX IF NOT EXISTS idx_user_alert_user ON user_alert(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
