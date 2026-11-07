package api

import (
	"bytes"
	"context"
	"crypto/tls"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"mime/multipart"
	"net"
	"net/http"
	"sort"
	"strings"
	"time"

	"github.com/unikii/dsentry/node/types"
)

type Client struct {
	BaseURL string
	PushKey string
	HTTP    *http.Client
}

type HTTPError struct {
	StatusCode int
	Body       string
}

func (e *HTTPError) Error() string {
	return fmt.Sprintf("HTTP %d: %s", e.StatusCode, e.Body)
}

func HTTPStatus(err error) int {
	var httpErr *HTTPError
	if errors.As(err, &httpErr) {
		return httpErr.StatusCode
	}
	return 0
}

type APIError struct {
	Operation string
	Status    int
	Message   string
}

func (e *APIError) Error() string {
	return fmt.Sprintf("%s failed: status=%d, msg=%s", e.Operation, e.Status, e.Message)
}

func APIStatus(err error) int {
	var apiErr *APIError
	if errors.As(err, &apiErr) {
		return apiErr.Status
	}
	return 0
}

func NewClient(baseURL, pushKey string, insecure bool) *Client {
	// Normalize here too so callers cannot accidentally build `//nodes`.
	baseURL = strings.TrimRight(strings.TrimSpace(baseURL), "/")
	transport := &http.Transport{
		DialContext: (&net.Dialer{
			Timeout:   15 * time.Second,
			KeepAlive: 30 * time.Second,
		}).DialContext,
		TLSHandshakeTimeout:   15 * time.Second,
		ResponseHeaderTimeout: 30 * time.Second,
		ExpectContinueTimeout: 1 * time.Second,
		MaxIdleConns:          10,
		IdleConnTimeout:       90 * time.Second,
		TLSClientConfig: &tls.Config{
			MinVersion:         tls.VersionTLS12,
			InsecureSkipVerify: insecure,
		},
	}

	return &Client{
		BaseURL: baseURL,
		PushKey: pushKey,
		HTTP: &http.Client{
			Transport: transport,
			Timeout:   120 * time.Second,
		},
	}
}

func wrapErr(err error, url string) error {
	if err == nil {
		return nil
	}
	msg := err.Error()
	if strings.Contains(msg, "TLS handshake timeout") {
		return fmt.Errorf("%w\n  Hint: Check that the server is reachable on port 443 and that no firewall is blocking TLS traffic to %s", err, url)
	}
	if strings.Contains(msg, "no such host") || strings.Contains(msg, "i/o timeout") {
		return fmt.Errorf("%w\n  Hint: Verify DNS resolution and network connectivity to %s", err, url)
	}
	if strings.Contains(msg, "certificate") {
		return fmt.Errorf("%w\n  Hint: The server's TLS certificate could not be verified. Ensure system CA certificates are installed (e.g. apt install ca-certificates). URL: %s", err, url)
	}
	return err
}

const maxHTTPErrorBody = 4096

func (c *Client) doContext(
	ctx context.Context,
	method string,
	endpoint string,
	body io.Reader,
	contentType string,
	result any,
) error {
	url := c.BaseURL + endpoint
	req, err := http.NewRequestWithContext(ctx, method, url, body)
	if err != nil {
		return err
	}
	req.Header.Set("Authorization", "Bearer "+c.PushKey)
	if contentType != "" {
		req.Header.Set("Content-Type", contentType)
	}

	resp, err := c.HTTP.Do(req)
	if err != nil {
		return wrapErr(err, url)
	}
	defer resp.Body.Close()

	if resp.StatusCode >= 400 {
		body, _ := io.ReadAll(io.LimitReader(resp.Body, maxHTTPErrorBody))
		return &HTTPError{StatusCode: resp.StatusCode, Body: string(body)}
	}

	if result == nil {
		return nil
	}
	return json.NewDecoder(resp.Body).Decode(result)
}

func (c *Client) getContext(ctx context.Context, endpoint string, result any) error {
	return c.doContext(ctx, http.MethodGet, endpoint, nil, "", result)
}

func (c *Client) postContext(ctx context.Context, endpoint string, body any, result any) error {
	data, err := json.Marshal(body)
	if err != nil {
		return err
	}

	return c.doContext(ctx, http.MethodPost, endpoint, bytes.NewReader(data), "application/json", result)
}

func (c *Client) RegisterNodeContext(ctx context.Context, hostname, hostOS string) (*types.RegisterNodeResponse, error) {
	req := types.RegisterNodeRequest{
		PushKey:  c.PushKey,
		Hostname: hostname,
		HostOS:   hostOS,
	}
	var resp types.RegisterNodeResponse
	if err := c.postContext(ctx, "/nodes", req, &resp); err != nil {
		return nil, err
	}
	if resp.Status != 0 {
		return &resp, &APIError{Operation: "register node", Status: resp.Status, Message: resp.Message}
	}
	return &resp, nil
}

func (c *Client) RegisterDevicesContext(ctx context.Context, nodeID int, devices []types.DeviceRegistration) (*types.RegisterDevicesResponse, error) {
	req := types.RegisterDevicesRequest{
		Devices: devices,
	}
	var resp types.RegisterDevicesResponse
	if err := c.postContext(ctx, fmt.Sprintf("/nodes/%d/devices", nodeID), req, &resp); err != nil {
		return nil, err
	}
	if resp.Status != 0 {
		return &resp, &APIError{Operation: "register devices", Status: resp.Status, Message: resp.Message}
	}
	return &resp, nil
}

func (c *Client) GetConfigContext(ctx context.Context, nodeID int) (*types.ConfigResponse, error) {
	endpoint := fmt.Sprintf("/nodes/%d/configs", nodeID)
	var resp types.ConfigResponse
	if err := c.getContext(ctx, endpoint, &resp); err != nil {
		return nil, err
	}
	if resp.Status != 0 {
		return &resp, &APIError{Operation: "get config", Status: resp.Status, Message: resp.Message}
	}
	return &resp, nil
}

func (c *Client) PushMetricsContext(ctx context.Context, nodeID int, metrics []interface{}) error {
	req := types.MetricsPushRequest{
		SchemaVersion: types.MetricsSchemaVersion,
		Metrics:       metrics,
	}
	var resp types.MetricsPushResponse
	if err := c.postContext(ctx, fmt.Sprintf("/nodes/%d/metrics", nodeID), req, &resp); err != nil {
		return err
	}
	if resp.Status != 0 {
		return &APIError{Operation: "push metrics", Status: resp.Status, Message: resp.Message}
	}
	return nil
}

func (c *Client) PushRawsContext(ctx context.Context, nodeID int, raws map[int]types.RawEntry) error {
	var resp types.RawsPushResponse
	if err := c.pushMultipartContext(ctx, fmt.Sprintf("/nodes/%d/raws", nodeID), raws, nil, &resp); err != nil {
		return err
	}
	if resp.Status != 0 {
		return &APIError{Operation: "push raws", Status: resp.Status, Message: resp.Message}
	}
	return nil
}

func (c *Client) PushEventsContext(ctx context.Context, nodeID int, events []types.DeviceEvent) error {
	raws := make(map[int]types.RawEntry)
	for _, evt := range events {
		if len(evt.RawData) > 0 {
			raws[evt.DeviceID] = types.RawEntry{
				Data:        evt.RawData,
				CollectedAt: evt.CollectedAt,
			}
		}
	}

	eventsJSON, err := json.Marshal(withoutRawData(events))
	if err != nil {
		return fmt.Errorf("marshal events: %w", err)
	}
	extraFields := map[string][]byte{"events": eventsJSON}

	var resp types.EventsPushResponse
	if err := c.pushMultipartContext(ctx, fmt.Sprintf("/nodes/%d/events", nodeID), raws, extraFields, &resp); err != nil {
		return err
	}
	if resp.Status != 0 {
		return &APIError{Operation: "push events", Status: resp.Status, Message: resp.Message}
	}
	return nil
}

// withoutRawData returns copies of the events with RawData cleared. The raw
// bytes already travel as multipart parts; keeping them in the JSON copy sent
// the same payload twice and could trip the hub's request-size limits.
func withoutRawData(events []types.DeviceEvent) []types.DeviceEvent {
	out := make([]types.DeviceEvent, len(events))
	copy(out, events)
	for i := range out {
		out[i].RawData = nil
	}
	return out
}

func (c *Client) pushMultipartContext(ctx context.Context, endpoint string, raws map[int]types.RawEntry, extraFields map[string][]byte, result any) error {
	var buf bytes.Buffer
	writer := multipart.NewWriter(&buf)

	type rawMeta struct {
		DeviceID    int    `json:"device_id"`
		CollectedAt string `json:"collected_at,omitempty"`
	}
	deviceIDs := make([]int, 0, len(raws))
	for deviceID := range raws {
		deviceIDs = append(deviceIDs, deviceID)
	}
	sort.Ints(deviceIDs)

	metaList := make([]rawMeta, 0, len(deviceIDs))
	for _, deviceID := range deviceIDs {
		entry := raws[deviceID]
		metaList = append(metaList, rawMeta{DeviceID: deviceID, CollectedAt: entry.CollectedAt})
		partName := fmt.Sprintf("%d", deviceID)
		part, err := writer.CreateFormFile(partName, fmt.Sprintf("%d.brotli", deviceID))
		if err != nil {
			return err
		}
		if _, err := part.Write(entry.Data); err != nil {
			return err
		}
	}

	metaJSON, err := json.Marshal(struct {
		Devices []rawMeta `json:"devices"`
	}{Devices: metaList})
	if err != nil {
		return fmt.Errorf("marshal raws meta: %w", err)
	}
	metaPart, err := writer.CreateFormField("meta")
	if err != nil {
		return fmt.Errorf("create meta field: %w", err)
	}
	if _, err := metaPart.Write(metaJSON); err != nil {
		return fmt.Errorf("write meta: %w", err)
	}

	extraFieldNames := make([]string, 0, len(extraFields))
	for fieldName := range extraFields {
		extraFieldNames = append(extraFieldNames, fieldName)
	}
	sort.Strings(extraFieldNames)
	for _, fieldName := range extraFieldNames {
		fieldData := extraFields[fieldName]
		part, err := writer.CreateFormField(fieldName)
		if err != nil {
			return fmt.Errorf("create extra field %s: %w", fieldName, err)
		}
		if _, err := part.Write(fieldData); err != nil {
			return fmt.Errorf("write extra field %s: %w", fieldName, err)
		}
	}

	if err := writer.Close(); err != nil {
		return err
	}

	return c.doContext(ctx, http.MethodPost, endpoint, &buf, writer.FormDataContentType(), result)
}

func (c *Client) PushMetasContext(ctx context.Context, nodeID int, metas []types.DeviceMetaEntry) ([]types.MetaPushResult, error) {
	req := types.MetaPushRequest{
		Metas: metas,
	}
	var resp types.MetaPushResponse
	if err := c.postContext(ctx, fmt.Sprintf("/nodes/%d/metas", nodeID), req, &resp); err != nil {
		return nil, err
	}
	if resp.Status != 0 {
		return nil, &APIError{Operation: "push metas", Status: resp.Status, Message: resp.Message}
	}
	return resp.Payload.Results, nil
}
