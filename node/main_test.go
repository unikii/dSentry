package main

import (
	"context"
	"errors"
	"fmt"
	"testing"

	"github.com/unikii/dsentry/node/loop"
	"github.com/unikii/dsentry/node/types"
)

func TestNeedsNodeRegistration(t *testing.T) {
	cases := []struct {
		name         string
		nodeID       int
		registerOnly bool
		want         bool
	}{
		{name: "fresh node registers", nodeID: 0, want: true},
		{name: "registered node skips registration", nodeID: 42, want: false},
		{
			name:         "register flag re-verifies a stored identity",
			nodeID:       42,
			registerOnly: true,
			want:         true,
		},
		{
			name:         "register flag on a fresh node",
			nodeID:       0,
			registerOnly: true,
			want:         true,
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			state := &types.NodeState{NodeID: tc.nodeID}
			if got := needsNodeRegistration(state, tc.registerOnly); got != tc.want {
				t.Fatalf(
					"needsNodeRegistration(nodeID=%d, registerOnly=%v) = %v, want %v",
					tc.nodeID, tc.registerOnly, got, tc.want,
				)
			}
		})
	}
}

func TestExitCode(t *testing.T) {
	cases := []struct {
		name string
		err  error
		want int
	}{
		{name: "success", err: nil, want: 0},
		{name: "cancelled", err: fmt.Errorf("stopped: %w", context.Canceled), want: 0},
		{name: "deadline exceeded", err: context.DeadlineExceeded, want: 0},
		{
			name: "fatal identity error",
			err:  fmt.Errorf("%w: node has been deleted", loop.ErrFatal),
			want: 2,
		},
		{name: "transient error", err: errors.New("hub unreachable"), want: 1},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := exitCode(tc.err); got != tc.want {
				t.Fatalf("exitCode(%v) = %d, want %d", tc.err, got, tc.want)
			}
		})
	}
}
