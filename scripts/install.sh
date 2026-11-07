#!/bin/sh
set -e

# dsnode one-line installer for Linux & macOS
#
# Usage (behind Caddy/Nginx, the API base is https://hub.example.com/api;
# when connecting directly to the hub API it is http://hub.example.com:9090):
#   export GITHUB_REPO=unikii/dsentry
#   curl -fsSL https://raw.githubusercontent.com/${GITHUB_REPO}/master/scripts/install.sh | sudo GITHUB_REPO="$GITHUB_REPO" sh -s -- "https://hub.example.com/api" "uuid_push_key"
#
# Or download and run:
#   chmod +x install.sh
#   sudo ./install.sh "https://hub.example.com/api" "uuid_push_key"
#
# Safe to re-run for upgrades: the download is verified before it
# replaces the live binary, and dsnode.toml / dsnode.json are preserved.

GITHUB_REPO="${GITHUB_REPO:-unikii/dsentry}"
API_ENDPOINT="${1:-}"
PUSH_KEY="${2:-}"
INSTALL_DIR="${INSTALL_DIR:-/opt/dSentry}"

RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m'

if [ -z "$API_ENDPOINT" ] || [ -z "$PUSH_KEY" ]; then
    echo "${RED}Error: API endpoint and push key are required.${NC}"
    echo "Usage: $0 \"https://hub.example.com/api\" \"uuid_push_key\""
    exit 1
fi

if [ -z "$GITHUB_REPO" ]; then
    echo "${RED}Error: GITHUB_REPO is not set (e.g. export GITHUB_REPO=unikii/dsentry).${NC}"
    exit 1
fi

GITHUB_RELEASES="https://github.com/${GITHUB_REPO}/releases"
echo "${GREEN}=== dsnode Installer ===${NC}"

os_name="$(uname -s | tr '[:upper:]' '[:lower:]')"
case "$os_name" in
    linux)  os="linux" ;;
    darwin) os="darwin" ;;
    *)
        echo "${RED}Unsupported OS: $os_name${NC}"
        exit 1
        ;;
esac

arch_name="$(uname -m)"
case "$arch_name" in
    x86_64|amd64) arch="amd64" ;;
    aarch64|arm64) arch="arm64" ;;
    armv7l)
        arch="arm"
        echo "${CYAN}32-bit ARMv7 detected, using arm binary${NC}"
        ;;
    *)
        echo "${RED}Unsupported architecture: $arch_name${NC}"
        exit 1
        ;;
esac

binary="dsnode-${os}-${arch}"
download_url="${GITHUB_RELEASES}/latest/download/${binary}"
checksum_url="${GITHUB_RELEASES}/latest/download/${binary}.sha256"

echo "Platform: ${os}/${arch}"
echo "Install dir: ${INSTALL_DIR}"
echo "Downloading: ${download_url}"

if [ "$(id -u)" -ne 0 ]; then
    echo "${RED}This installer must be run as root (sudo).${NC}"
    exit 1
fi

if ! command -v smartctl >/dev/null 2>&1 && [ "${SKIP_SMARTCTL_CHECK:-}" != "1" ]; then
    echo "${RED}Error: 'smartctl' (smartmontools) not found on PATH.${NC}"
    echo "dsnode shells out to smartctl for every scan, so it cannot report anything without it."
    if [ "$os" = "darwin" ]; then
        echo "Install it with: brew install smartmontools"
    else
        echo "Install it with: sudo apt install smartmontools  (or the dnf/yum equivalent)"
    fi
    echo "Then re-run this installer, or bypass with: SKIP_SMARTCTL_CHECK=1"
    exit 1
fi

mkdir -p "${INSTALL_DIR}"

WAS_RUNNING=0
if command -v pgrep >/dev/null 2>&1 && pgrep -f "${INSTALL_DIR}/dsnode" >/dev/null 2>&1; then
    WAS_RUNNING=1
    echo "${CYAN}Note: dsnode is currently running — the binary will be replaced atomically; restart afterwards to pick it up.${NC}"
fi

# Download to temp files first: writing straight onto a running binary
# fails on Linux (ETXTBSY), and a half-written download must never
# replace a working binary.
TMP_BIN="${INSTALL_DIR}/.dsnode.new"
TMP_SUM="${INSTALL_DIR}/.dsnode.new.sha256"
rm -f "$TMP_BIN" "$TMP_SUM"

if command -v curl >/dev/null 2>&1; then
    curl -fsSL "${download_url}" -o "$TMP_BIN"
    curl -fsSL "${checksum_url}" -o "$TMP_SUM"
elif command -v wget >/dev/null 2>&1; then
    wget -q "${download_url}" -O "$TMP_BIN"
    wget -q "${checksum_url}" -O "$TMP_SUM"
else
    echo "${RED}Neither curl nor wget found. Install one of them and retry.${NC}"
    exit 1
fi

# The .sha256 file lists the release artifact name ("<hash>  dsnode-<os>-<arch>"),
# not our local filename, so compare hashes field-wise instead of `sha256sum -c`.
if command -v sha256sum >/dev/null 2>&1; then
    expected_hash=$(awk '{print $1}' "$TMP_SUM" | tr 'A-Z' 'a-z')
    actual_hash=$(sha256sum "$TMP_BIN" | awk '{print $1}' | tr 'A-Z' 'a-z')
elif command -v shasum >/dev/null 2>&1; then
    expected_hash=$(awk '{print $1}' "$TMP_SUM" | tr 'A-Z' 'a-z')
    actual_hash=$(shasum -a 256 "$TMP_BIN" | awk '{print $1}' | tr 'A-Z' 'a-z')
else
    echo "${RED}Neither sha256sum nor shasum found. Cannot verify checksum.${NC}"
    rm -f "$TMP_BIN" "$TMP_SUM"
    exit 1
fi

if [ -z "$expected_hash" ] || [ "$expected_hash" != "$actual_hash" ]; then
    echo "${RED}Checksum verification failed!${NC}"
    rm -f "$TMP_BIN" "$TMP_SUM"
    exit 1
fi

rm -f "$TMP_SUM"
chmod +x "$TMP_BIN"
mv -f "$TMP_BIN" "${INSTALL_DIR}/dsnode"
echo "${GREEN}Binary installed and verified.${NC}"

echo ""
echo "Registering node with dSentry..."
node_output=$("${INSTALL_DIR}/dsnode" \
    -register \
    -api-endpoint "${API_ENDPOINT}" \
    -push-key "${PUSH_KEY}" 2>&1) || {
    echo "${RED}Registration failed:${NC}"
    echo "$node_output"
    exit 1
}
echo "$node_output"

echo ""
echo "${GREEN}=== dsnode installed successfully ===${NC}"
echo ""
echo "To run manually:"
echo "  ${INSTALL_DIR}/dsnode"
echo ""
if [ "$WAS_RUNNING" = "1" ] || [ -f /etc/systemd/system/dsnode.service ]; then
    echo "dsnode was already installed — restart the service to pick up the new binary:"
    echo "  sudo systemctl restart dsnode"
    echo ""
fi
echo "To install as a systemd service:"
echo "  sudo tee /etc/systemd/system/dsnode.service <<'EOF'"
echo "  [Unit]"
echo "  Description=dsnode - Storage Health Monitor"
echo "  After=network-online.target"
echo "  Wants=network-online.target"
echo ""
echo "  [Service]"
echo "  Type=simple"
echo "  ExecStart=${INSTALL_DIR}/dsnode"
echo "  Restart=on-failure"
echo "  RestartSec=60"
echo "  RestartPreventExitStatus=2"
echo ""
echo "  [Install]"
echo "  WantedBy=multi-user.target"
echo "  EOF"
echo ""
echo "  sudo systemctl daemon-reload"
echo "  sudo systemctl enable --now dsnode"
