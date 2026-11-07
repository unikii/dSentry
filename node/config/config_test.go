package config

import (
	"os"
	"path/filepath"
	"runtime"
	"testing"

	"github.com/unikii/dsentry/node/types"
)

func TestNormalizeEndpoint(t *testing.T) {
	cases := map[string]string{
		"http://host:9090":    "http://host:9090",
		"http://host:9090/":   "http://host:9090",
		" https://host/api/ ": "https://host/api",
		"https://host/api///": "https://host/api",
		"https://host/api":    "https://host/api",
	}
	for input, want := range cases {
		if got := NormalizeEndpoint(input); got != want {
			t.Errorf("NormalizeEndpoint(%q) = %q, want %q", input, got, want)
		}
	}
}

func TestStateSaveUsesPrivatePermissions(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("Windows does not expose Unix permission bits")
	}

	path := filepath.Join(t.TempDir(), "dsnode.json")
	manager := NewStateManager(path)
	if err := manager.Save(&types.NodeState{PushKey: "secret", Devices: map[string]types.DeviceState{}}); err != nil {
		t.Fatal(err)
	}

	info, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	if mode := info.Mode().Perm(); mode != 0600 {
		t.Fatalf("state permissions = %04o, want 0600", mode)
	}
}
