package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"github.com/unikii/dsentry/node/api"
	"github.com/unikii/dsentry/node/config"
	"github.com/unikii/dsentry/node/logutil"
	"github.com/unikii/dsentry/node/loop"
	"github.com/unikii/dsentry/node/scanner"
	smartctl "github.com/unikii/dsentry/node/smartctl"
	"log"
	"net"
	"net/url"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"runtime"
	"syscall"
	"time"

	"github.com/unikii/dsentry/node/types"
)

var Version = "dev"

func main() {
	err := run()
	if err != nil {
		log.Printf("dsnode stopped: %v", err)
	}
	if code := exitCode(err); code != 0 {
		os.Exit(code)
	}
}

// exitCode maps run()'s error to a process exit status.
//
// Exit code 2 means "fatal identity/configuration error" (node deleted,
// invalid push key, device limit reached). The generated systemd unit sets
// RestartPreventExitStatus=2 so those do not restart-loop; transient errors
// exit 1 and are retried by the service manager.
func exitCode(err error) int {
	switch {
	case err == nil:
		return 0
	case errors.Is(err, context.Canceled), errors.Is(err, context.DeadlineExceeded):
		// Normal shutdown path (SIGINT/SIGTERM).
		return 0
	case errors.Is(err, loop.ErrFatal):
		return 2
	default:
		return 1
	}
}

// needsNodeRegistration reports whether startup must call the hub's register
// endpoint. A fresh node always registers; -register always re-verifies the
// stored identity instead of assuming the saved node ID is still valid.
func needsNodeRegistration(state *types.NodeState, registerOnly bool) bool {
	return registerOnly || state.NodeID == 0
}

func run() error {
	configPathFlag := flag.String("config", defaultConfigPath(), "Path to dsnode.toml")
	apiEndpoint := flag.String("api-endpoint", "", "dSentry API endpoint URL")
	pushKey := flag.String("push-key", "", "Push key for authentication")
	insecure := flag.Bool("insecure", false, "Skip TLS certificate verification")
	verbose := flag.Bool("verbose", false, "Enable detailed operational logging")
	version := flag.Bool("version", false, "Print version and exit")
	registerOnly := flag.Bool("register", false, "Register the node with the hub and exit")
	flag.Parse()

	if *version {
		fmt.Printf("dsnode v%s\n", Version)
		return nil
	}

	log.Printf("dsnode v%s starting", Version)
	log.Printf("Config: %s", *configPathFlag)

	if err := config.GenerateDefault(*configPathFlag); err != nil {
		log.Printf("Warning: could not generate default config: %v", err)
	}

	cfg, err := config.Load(*configPathFlag)
	if err != nil {
		return fmt.Errorf("load config: %w", err)
	}

	// Fail fast when smartctl is unavailable: every scan shells out to
	// it, so starting without it only produces a registered-but-silent
	// node. Checking before registration keeps the installer output
	// honest instead of reporting success and failing later.
	if err := checkSmartctlAvailable(cfg.Commands.SmartctlBin); err != nil {
		return err
	}

	if *verbose || cfg.Verbose {
		logutil.Verbose = true
	}

	statePath := filepath.Join(filepath.Dir(*configPathFlag), "dsnode.json")
	stateManager := config.NewStateManager(statePath)

	state, err := stateManager.Load()
	if err != nil {
		return fmt.Errorf("load state: %w", err)
	}

	if *apiEndpoint == "" && state.ApiEndpoint != "" {
		*apiEndpoint = state.ApiEndpoint
	}
	if *pushKey == "" && state.PushKey != "" {
		*pushKey = state.PushKey
	}

	// Trailing slashes must not turn into double-slash request paths, and
	// endpoint-only changes must compare equal to their normalized form.
	*apiEndpoint = config.NormalizeEndpoint(*apiEndpoint)

	if *apiEndpoint == "" {
		return errors.New("API endpoint is required. Use -api-endpoint flag or ensure dsnode.json has api_endpoint set")
	}
	if *pushKey == "" {
		return errors.New("push key is required. Use -push-key flag or ensure dsnode.json has push_key set")
	}

	log.Printf("API: %s", *apiEndpoint)

	if u, err := url.Parse(*apiEndpoint); err == nil {
		if addrs, err := net.LookupHost(u.Hostname()); err == nil {
			log.Printf("Resolved %s -> %v", u.Hostname(), addrs)
		} else {
			log.Printf("Warning: DNS lookup for %s failed: %v", u.Hostname(), err)
		}
	}

	hostname := smartctl.GetHostname()
	hostOS := smartctl.GetOSInfo()

	apiClient := api.NewClient(*apiEndpoint, *pushKey, *insecure)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)
	defer signal.Stop(sigCh)
	go func() {
		select {
		case <-sigCh:
			log.Println("Shutting down dsnode...")
			cancel()
		case <-ctx.Done():
		}
	}()

	// Credentials changed since last run (reinstall with a new push key):
	// the saved node ID belongs to the old credentials and the hub would
	// reject every push with 401/101. Discard it — along with per-node
	// device IDs and queued pushes — and register again.
	//
	// An endpoint-only change is NOT an identity change: the same node keeps
	// its ID, devices, and outbox. Re-registration is idempotent on the hub,
	// so -register re-verifies the identity without creating a new node.
	if state.NodeID != 0 && state.PushKey != *pushKey {
		log.Printf("Push key changed — discarding old node ID %d and re-registering", state.NodeID)
		state.NodeID = 0
		state.Devices = make(map[string]types.DeviceState)
		state.Outbox = nil
	} else if state.NodeID != 0 && config.NormalizeEndpoint(state.ApiEndpoint) != *apiEndpoint {
		log.Printf("API endpoint changed (%s -> %s) — keeping node ID %d", state.ApiEndpoint, *apiEndpoint, state.NodeID)
	}

	if needsNodeRegistration(state, *registerOnly) {
		// The hub may simply be down at boot; retry instead of crash-looping.
		// -register must always contact the hub, even when a node ID is
		// already stored: a stale ID (hub restored from an old backup, or an
		// endpoint change) must not be reported as a successful registration.
		log.Println("Registering node with dSentry...")
		var resp *types.RegisterNodeResponse
		attempts := 0
		for {
			resp, err = apiClient.RegisterNodeContext(ctx, hostname, hostOS)
			if err == nil {
				break
			}
			if ctx.Err() != nil {
				return ctx.Err()
			}
			if api.APIStatus(err) == types.StatusNodeNotRegistered ||
				api.HTTPStatus(err) == 401 || api.HTTPStatus(err) == 403 {
				return fmt.Errorf("%w: register node: %v", loop.ErrFatal, err)
			}
			// The installer runs with -register and must terminate with an
			// error instead of hanging forever when the hub is unreachable.
			if *registerOnly {
				attempts++
				if attempts >= 5 {
					return fmt.Errorf("register node: %w", err)
				}
			}
			log.Printf("Node registration failed: %v — retrying in 30s", err)
			if err := sleepCtx(ctx, 30*time.Second); err != nil {
				return err
			}
		}
		state.NodeID = resp.Payload.NodeID
		state.PushKey = *pushKey
		state.ApiEndpoint = *apiEndpoint
		if err := stateManager.Save(state); err != nil {
			return fmt.Errorf("save state: %w", err)
		}
		log.Printf("Node registered: ID=%d", state.NodeID)
	} else {
		state.PushKey = *pushKey
		state.ApiEndpoint = *apiEndpoint
		if err := stateManager.Save(state); err != nil {
			log.Printf("Warning: failed to save state: %v", err)
		}
	}

	if *registerOnly {
		log.Println("Registration complete")
		return nil
	}

	sc := scanner.New(cfg)

	pl := loop.New(apiClient, cfg, stateManager, sc, state.NodeID)

	return pl.RunWithContext(ctx)
}

func sleepCtx(ctx context.Context, d time.Duration) error {
	timer := time.NewTimer(d)
	defer timer.Stop()
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-timer.C:
		return nil
	}
}

func defaultConfigPath() string {
	exe, err := os.Executable()
	if err != nil {
		exe = "."
	}
	return filepath.Join(filepath.Dir(exe), "dsnode.toml")
}

func checkSmartctlAvailable(bin string) error {
	if bin == "" {
		bin = "smartctl"
	}
	if _, err := exec.LookPath(bin); err != nil {
		var hint string
		switch runtime.GOOS {
		case "windows":
			hint = "install smartmontools from https://www.smartmontools.org/wiki/Download (tick 'Add to PATH' during setup)"
		case "darwin":
			hint = "install smartmontools via 'brew install smartmontools'"
		default:
			hint = "install smartmontools via your package manager (e.g. 'apt install smartmontools')"
		}
		return fmt.Errorf("smartctl not found (%q): %s", bin, hint)
	}
	return nil
}
