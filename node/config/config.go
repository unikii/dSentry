package config

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/BurntSushi/toml"
	"github.com/unikii/dsentry/node/types"
)

// NormalizeEndpoint makes equivalent API endpoints compare equal: surrounding
// whitespace and trailing slashes are insignificant (a trailing slash used to
// produce double-slash request paths such as `//nodes`).
func NormalizeEndpoint(raw string) string {
	return strings.TrimRight(strings.TrimSpace(raw), "/")
}

type Config struct {
	Verbose  bool             `toml:"verbose"`
	Commands CommandsConfig   `toml:"commands"`
	Devices  []DeviceOverride `toml:"devices"`
}

type CommandsConfig struct {
	SmartctlBin      string `toml:"smartctl_bin"`
	MetricsScanArgs  string `toml:"metrics_scan_args"`
	MetricsSmartArgs string `toml:"metrics_smart_args"`
	SmartctlWait     int    `toml:"smartctl_wait"`
}

type DeviceOverride struct {
	Device   string   `toml:"device"`
	Type     []string `toml:"type"`
	Ignore   bool     `toml:"ignore"`
	Commands struct {
		MetricsSmartArgs string `toml:"metrics_smart_args"`
	} `toml:"commands"`
}

func DefaultConfig() Config {
	return Config{
		Verbose: false,
		Commands: CommandsConfig{
			SmartctlBin:      "smartctl",
			MetricsScanArgs:  "--scan --json",
			MetricsSmartArgs: "-x --json",
			SmartctlWait:     0,
		},
	}
}

func Load(path string) (*Config, error) {
	cfg := DefaultConfig()

	if _, err := os.Stat(path); os.IsNotExist(err) {
		return &cfg, nil
	}

	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("reading config file: %w", err)
	}

	if err := toml.Unmarshal(data, &cfg); err != nil {
		return nil, fmt.Errorf("parsing config file: %w", err)
	}

	return &cfg, nil
}

func (c *Config) GetCommandMetricsSmartArgs(deviceName string) string {
	for _, dev := range c.Devices {
		if dev.Device == deviceName && dev.Commands.MetricsSmartArgs != "" {
			return dev.Commands.MetricsSmartArgs
		}
	}
	return c.Commands.MetricsSmartArgs
}

func GenerateDefault(path string) error {
	if _, err := os.Stat(path); err == nil {
		return nil
	}

	cfg := DefaultConfig()
	dir := filepath.Dir(path)
	if err := os.MkdirAll(dir, 0755); err != nil {
		return fmt.Errorf("creating config dir: %w", err)
	}

	f, err := os.Create(path)
	if err != nil {
		return fmt.Errorf("creating config file: %w", err)
	}
	defer f.Close()

	encoder := toml.NewEncoder(f)
	return encoder.Encode(cfg)
}

type StateManager struct {
	path string
}

func NewStateManager(path string) *StateManager {
	return &StateManager{path: path}
}

func (s *StateManager) Load() (*types.NodeState, error) {
	state := &types.NodeState{
		Devices: make(map[string]types.DeviceState),
	}

	data, err := os.ReadFile(s.path)
	if err != nil {
		if os.IsNotExist(err) {
			return state, nil
		}
		return nil, fmt.Errorf("reading state file: %w", err)
	}

	if len(data) == 0 {
		return state, nil
	}

	if err := json.Unmarshal(data, state); err != nil {
		return nil, fmt.Errorf("parsing state file: %w", err)
	}

	if state.Devices == nil {
		state.Devices = make(map[string]types.DeviceState)
	}

	return state, nil
}

func (s *StateManager) Save(state *types.NodeState) error {
	data, err := json.MarshalIndent(state, "", "  ")
	if err != nil {
		return fmt.Errorf("marshaling state: %w", err)
	}

	dir := filepath.Dir(s.path)
	if err := os.MkdirAll(dir, 0755); err != nil {
		return err
	}

	tmpPath := s.path + ".tmp"
	f, err := os.OpenFile(tmpPath, os.O_WRONLY|os.O_CREATE|os.O_TRUNC, 0600)
	if err != nil {
		return fmt.Errorf("creating temp file: %w", err)
	}
	if err := f.Chmod(0600); err != nil {
		f.Close()
		os.Remove(tmpPath)
		return fmt.Errorf("setting temp file permissions: %w", err)
	}
	if _, err := f.Write(data); err != nil {
		f.Close()
		os.Remove(tmpPath)
		return fmt.Errorf("writing temp file: %w", err)
	}
	if err := f.Sync(); err != nil {
		f.Close()
		os.Remove(tmpPath)
		return fmt.Errorf("syncing temp file: %w", err)
	}
	if err := f.Close(); err != nil {
		os.Remove(tmpPath)
		return fmt.Errorf("closing temp file: %w", err)
	}

	if err := os.Rename(tmpPath, s.path); err != nil {
		os.Remove(tmpPath)
		return fmt.Errorf("renaming temp file: %w", err)
	}

	// fsync the directory so the rename itself survives a crash on
	// filesystems that journal data separately from metadata.
	if dirHandle, err := os.Open(dir); err == nil {
		_ = dirHandle.Sync()
		_ = dirHandle.Close()
	}

	return nil
}
