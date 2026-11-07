package smartctl

import (
	"bytes"
	"encoding/json"
	"fmt"

	"github.com/andybalholm/brotli"
)

type ParsedOutput struct {
	Output   *SmartctlOutput
	Protocol string
	Metrics  *DeviceMetrics
	Parser   ProtocolParser
	// MetricsErr is set when the SMART JSON parsed but its metrics could not
	// be extracted (e.g. a missing NVMe health log). Health status, metadata,
	// and raw output are still usable in that case; only the metrics are not.
	MetricsErr error
}

func ParseOutput(rawJSON []byte) (*ParsedOutput, error) {
	var output SmartctlOutput
	if err := json.Unmarshal(rawJSON, &output); err != nil {
		return nil, fmt.Errorf("unmarshal smartctl output: %w", err)
	}
	output.Normalize()

	protocol, err := DetectProtocol(&output)
	if err != nil {
		return nil, fmt.Errorf("detect protocol: %w", err)
	}

	parser, err := GetParser(protocol)
	if err != nil {
		return nil, fmt.Errorf("get parser for %s: %w", protocol, err)
	}

	// A metrics failure must not hide the SMART pass/fail status: health
	// monitoring must still emit status events when the attribute/health log
	// layout is unexpected.
	metrics, metricsErr := parser.ParseMetrics(&output)

	return &ParsedOutput{
		Output:     &output,
		Protocol:   protocol,
		Metrics:    metrics,
		Parser:     parser,
		MetricsErr: metricsErr,
	}, nil
}

func ComputeSmartStatus(output *SmartctlOutput) int {
	if output.SMARTStatus == nil {
		return 2
	}
	if output.SMARTStatus.Passed {
		return 0
	}
	return 1
}

func MetricsToMap(m *DeviceMetrics) (map[string]interface{}, error) {
	data, err := json.Marshal(m)
	if err != nil {
		return nil, fmt.Errorf("marshal metrics: %w", err)
	}
	var result map[string]interface{}
	if err := json.Unmarshal(data, &result); err != nil {
		return nil, fmt.Errorf("unmarshal metrics to map: %w", err)
	}
	return result, nil
}

func CompressRawOutput(rawJSON []byte, rawPlain []byte) ([]byte, error) {
	raw := map[string]string{
		"json": string(rawJSON),
	}
	if len(rawPlain) > 0 {
		raw["plain"] = string(rawPlain)
	}
	rawJSONBytes, err := json.Marshal(raw)
	if err != nil {
		return nil, err
	}

	var buf bytes.Buffer
	writer := brotli.NewWriter(&buf)
	if _, err := writer.Write(rawJSONBytes); err != nil {
		return nil, err
	}
	if err := writer.Close(); err != nil {
		return nil, err
	}

	return buf.Bytes(), nil
}
