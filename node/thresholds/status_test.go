package thresholds

import "testing"

func TestNvmeTemperatureThresholds(t *testing.T) {
	health := &NvmeHealthInput{
		Temperature:               80,
		WarnCompTempThreshold:     75,
		CriticalCompTempThreshold: 85,
		AvailableSpare:            100,
		AvailableSpareThreshold:   10,
	}

	results, overall := ComputeNvmeAttributeStatuses(health)
	if results["temperature"].Status != AttrStatusWarning {
		t.Fatalf("expected warning, got %q", results["temperature"].Status)
	}
	if overall != SMARTThresholdStatusWarning {
		t.Fatalf("expected overall warning, got %d", overall)
	}

	health.Temperature = 90
	results, overall = ComputeNvmeAttributeStatuses(health)
	if results["temperature"].Status != AttrStatusFailed {
		t.Fatalf("expected failure, got %q", results["temperature"].Status)
	}
	if overall != SMARTThresholdStatusFailed {
		t.Fatalf("expected overall failure, got %d", overall)
	}
}
