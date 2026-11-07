#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILD_NUM_FILE="$SCRIPT_DIR/.buildnum"
DIST_DIR="$SCRIPT_DIR/dist"

if [[ -f "$BUILD_NUM_FILE" ]]; then
  BUILD_NUM=$(($(cat "$BUILD_NUM_FILE") + 1))
else
  BUILD_NUM=1
fi
echo "$BUILD_NUM" > "$BUILD_NUM_FILE"

GIT_COMMIT=$(git -C "$SCRIPT_DIR" rev-parse --short=7 HEAD 2>/dev/null || echo "unknown")
BUILD_TIME=$(date -u +%Y-%m-%dT%H:%M:%SZ)

VERSION="${BUILD_NUM} (${BUILD_TIME} commit=${GIT_COMMIT})"
LDFLAGS="-s -w -X 'main.Version=${VERSION}'"

mkdir -p "$DIST_DIR"

build_one() {
	local goos="$1"
	local goarch="$2"
	local ext="$3"
	local out="$DIST_DIR/dsnode-${goos}-${goarch}${ext}"

	echo "  ${goos}/${goarch} -> ${out}"
	GOOS="$goos" GOARCH="$goarch" go build -ldflags="${LDFLAGS}" -o "$out" "$SCRIPT_DIR"
}

echo "==> dsnode v${VERSION}"
echo

build_one linux   amd64 ""
build_one linux   arm64 ""
build_one darwin  amd64 ""
build_one darwin  arm64 ""
build_one windows amd64 ".exe"
build_one windows arm64 ".exe"

echo
echo "==> Done:"
ls -lh "$DIST_DIR"
