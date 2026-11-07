package smartctl

import (
	"bufio"
	"fmt"
	"os"
	"os/exec"
	"runtime"
	"strings"
)

func GetHostname() string {
	name, err := os.Hostname()
	if err != nil {
		return "unknown"
	}
	return name
}

func GetOSInfo() string {
	switch runtime.GOOS {
	case "linux":
		return getLinuxOSInfo()
	case "darwin":
		return getDarwinOSInfo()
	case "windows":
		return getWindowsOSInfo()
	default:
		return runtime.GOOS
	}
}

func getLinuxOSInfo() string {
	data, err := os.ReadFile("/etc/os-release")
	if err != nil {
		return "linux"
	}
	var name, version string
	scanner := bufio.NewScanner(strings.NewReader(string(data)))
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		switch {
		case strings.HasPrefix(line, "ID="):
			name = unquote(strings.TrimPrefix(line, "ID="))
		case strings.HasPrefix(line, "VERSION_ID="):
			version = unquote(strings.TrimPrefix(line, "VERSION_ID="))
		}
	}
	if name != "" && version != "" {
		return fmt.Sprintf("%s %s", titleCase(name), version)
	}
	if name != "" {
		return name
	}
	return "linux"
}

func titleCase(s string) string {
	if len(s) == 0 {
		return s
	}
	return strings.ToUpper(s[:1]) + s[1:]
}

func getDarwinOSInfo() string {
	out, err := exec.Command("sw_vers", "-productName").Output()
	if err != nil {
		return "macos"
	}
	name := strings.TrimSpace(string(out))
	verOut, err := exec.Command("sw_vers", "-productVersion").Output()
	if err != nil {
		return name
	}
	version := strings.TrimSpace(string(verOut))
	return name + " " + version
}

func getWindowsOSInfo() string {
	out, err := exec.Command("cmd", "/c", "ver").Output()
	if err != nil {
		return "windows"
	}
	line := strings.TrimSpace(string(out))
	if strings.HasPrefix(line, "Microsoft Windows ") {
		rest := strings.TrimPrefix(line, "Microsoft Windows ")
		rest = strings.TrimSuffix(rest, ".")
		if idx := strings.Index(rest, "["); idx > 0 {
			rest = strings.TrimSpace(rest[:idx])
		}
		return "Windows " + rest
	}
	return "windows"
}

func unquote(s string) string {
	s = strings.TrimSpace(s)
	if len(s) >= 2 && s[0] == '"' && s[len(s)-1] == '"' {
		return s[1 : len(s)-1]
	}
	return s
}
