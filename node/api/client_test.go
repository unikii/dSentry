package api

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/unikii/dsentry/node/types"
)

func TestNewClientNormalizesTrailingSlash(t *testing.T) {
	var gotPath string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotPath = r.URL.Path
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"status":0,"message":""}`))
	}))
	defer server.Close()

	client := NewClient(server.URL+"/", "key", false)
	if err := client.PushRawsContext(context.Background(), 7, map[int]types.RawEntry{3: {Data: []byte("raw")}}); err != nil {
		t.Fatal(err)
	}
	if gotPath != "/nodes/7/raws" {
		t.Fatalf("request path = %q, want /nodes/7/raws", gotPath)
	}
}

func TestPushMetasReturnsPerItemResults(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"status":0,"payload":{"results":[{"device_hash":"a","updated":false},{"device_hash":"b","updated":true}]}}`))
	}))
	defer server.Close()

	client := NewClient(server.URL, "key", false)
	results, err := client.PushMetasContext(context.Background(), 7, []types.DeviceMetaEntry{{DeviceHash: "a"}, {DeviceHash: "b"}})
	if err != nil {
		t.Fatal(err)
	}
	if len(results) != 2 || results[0].Updated || !results[1].Updated {
		t.Fatalf("results = %+v, want a=false b=true", results)
	}
}

func TestPushRawsReturnsEnvelopeFailure(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"status":1,"message":"raw push not required"}`))
	}))
	defer server.Close()

	client := &Client{BaseURL: server.URL, PushKey: "key", HTTP: server.Client()}
	err := client.PushRawsContext(context.Background(), 7, map[int]types.RawEntry{3: {Data: []byte("raw")}})
	if err == nil || !strings.Contains(err.Error(), "status=1") {
		t.Fatalf("expected envelope failure, got %v", err)
	}
	if got := APIStatus(err); got != 1 {
		t.Fatalf("APIStatus() = %d, want 1", got)
	}
}

func TestHTTPStatus(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, "invalid push key", http.StatusUnauthorized)
	}))
	defer server.Close()

	client := &Client{BaseURL: server.URL, PushKey: "bad", HTTP: server.Client()}
	_, err := client.GetConfigContext(context.Background(), 7)
	if got := HTTPStatus(err); got != http.StatusUnauthorized {
		t.Fatalf("HTTPStatus() = %d, want %d", got, http.StatusUnauthorized)
	}
}
