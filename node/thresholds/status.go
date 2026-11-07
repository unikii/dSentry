package thresholds

import (
	"strconv"
	"strings"
)

const (
	SMARTThresholdStatusPassed  = 0
	SMARTThresholdStatusWarning = 1
	SMARTThresholdStatusFailed  = 2
)

const (
	AttrStatusPassed  = "passed"
	AttrStatusWarning = "warning"
	AttrStatusFailed  = "failed"
)

type SmartAttrThresholdResult struct {
	AttributeID  string  `json:"attribute_id"`
	Status       string  `json:"status"`
	StatusReason string  `json:"status_reason,omitempty"`
	FailureRate  float64 `json:"failure_rate,omitempty"`
}

func ComputeAtaAttributeStatuses(attrs map[int]*AtaAttrInput) (map[string]SmartAttrThresholdResult, int) {
	results := make(map[string]SmartAttrThresholdResult)
	overallStatus := SMARTThresholdStatusPassed

	for id, attr := range attrs {
		result := computeSingleAtaStatus(id, attr)
		results[strconv.Itoa(id)] = result

		switch result.Status {
		case AttrStatusFailed:
			overallStatus = SMARTThresholdStatusFailed
		case AttrStatusWarning:
			if overallStatus == SMARTThresholdStatusPassed {
				overallStatus = SMARTThresholdStatusWarning
			}
		}
	}

	return results, overallStatus
}

func computeSingleAtaStatus(id int, attr *AtaAttrInput) SmartAttrThresholdResult {
	result := SmartAttrThresholdResult{
		AttributeID: strconv.Itoa(id),
		Status:      AttrStatusPassed,
	}

	if strings.ToUpper(attr.WhenFailed) == "FAILING_NOW" {
		result.Status = AttrStatusFailed
		result.StatusReason = "Attribute is failing manufacturer SMART threshold"
		return result
	}

	if strings.ToUpper(attr.WhenFailed) == "IN_THE_PAST" {
		result.Status = AttrStatusWarning
		result.StatusReason = "Attribute has previously failed manufacturer SMART threshold"
	}

	smartMetadata, ok := AtaMetadata[id]
	if !ok || len(smartMetadata.ObservedThresholds) == 0 {
		return result
	}

	var value int64
	switch smartMetadata.DisplayType {
	case AtaSmartAttributeDisplayTypeNormalized:
		value = int64(attr.Value)
	case AtaSmartAttributeDisplayTypeTransformed:
		value = attr.TransformedValue
	default:
		value = attr.RawValue
	}

	for _, obsThresh := range smartMetadata.ObservedThresholds {
		if ((obsThresh.Low == obsThresh.High) && value == obsThresh.Low) ||
			(obsThresh.Low <= value && value <= obsThresh.High) {
			result.FailureRate = obsThresh.AnnualFailureRate

			if smartMetadata.Critical {
				if obsThresh.AnnualFailureRate >= 0.10 {
					result.Status = AttrStatusFailed
					result.StatusReason = "Observed Failure Rate for Critical Attribute is greater than 10%"
				}
			} else {
				if obsThresh.AnnualFailureRate >= 0.20 {
					result.Status = AttrStatusFailed
					result.StatusReason = "Observed Failure Rate for Non-Critical Attribute is greater than 20%"
				} else if obsThresh.AnnualFailureRate >= 0.10 {
					if result.Status != AttrStatusFailed {
						result.Status = AttrStatusWarning
					}
					result.StatusReason = "Observed Failure Rate for Non-Critical Attribute is greater than 10%"
				}
			}
			return result
		}
	}

	if smartMetadata.Critical {
		if result.Status == AttrStatusPassed {
			result.Status = AttrStatusWarning
		}
		result.StatusReason = "Could not determine Observed Failure Rate for Critical Attribute"
	}

	return result
}

type AtaAttrInput struct {
	Value            int
	RawValue         int64
	RawString        string
	WhenFailed       string
	TransformedValue int64
}

func PrepareAtaTransformedValues(attrs map[int]*AtaAttrInput) {
	for id, attr := range attrs {
		smartMetadata, ok := AtaMetadata[id]
		if !ok || smartMetadata.Transform == nil {
			continue
		}
		attr.TransformedValue = smartMetadata.Transform(int64(attr.Value), attr.RawValue, attr.RawString)
	}
}

func ComputeNvmeAttributeStatuses(health *NvmeHealthInput) (map[string]SmartAttrThresholdResult, int) {
	attrs := []attrInput{
		{"critical_warning", int64(health.CriticalWarning), 0},
		{"available_spare", int64(health.AvailableSpare), int64(health.AvailableSpareThreshold)},
		{"percentage_used", int64(health.PercentageUsed), 100},
		{"media_errors", int64(health.MediaErrors), 0},
		{"num_err_log_entries", int64(health.NumErrLogEntries), -1},
	}

	meta := make(metadataLookup, len(NvmeMetadata))
	for k, v := range NvmeMetadata {
		meta[k] = attrMeta{Ideal: v.Ideal, Critical: v.Critical}
	}

	results, overallStatus := computeAttrResults(attrs, meta)

	// Temperature has no fixed numeric threshold in NvmeMetadata; use the
	// drive-reported warning/critical composite thresholds instead.
	if health.CriticalCompTempThreshold > 0 &&
		health.Temperature >= health.CriticalCompTempThreshold {
		results["temperature"] = SmartAttrThresholdResult{
			AttributeID:  "temperature",
			Status:       AttrStatusFailed,
			StatusReason: "Temperature reached the critical threshold",
		}
		overallStatus = SMARTThresholdStatusFailed
	} else if health.WarnCompTempThreshold > 0 &&
		health.Temperature >= health.WarnCompTempThreshold {
		results["temperature"] = SmartAttrThresholdResult{
			AttributeID:  "temperature",
			Status:       AttrStatusWarning,
			StatusReason: "Temperature reached the warning threshold",
		}
		if overallStatus == SMARTThresholdStatusPassed {
			overallStatus = SMARTThresholdStatusWarning
		}
	} else {
		results["temperature"] = SmartAttrThresholdResult{
			AttributeID: "temperature",
			Status:      AttrStatusPassed,
		}
	}

	infoAttrs := []string{"data_units_read", "data_units_written", "host_reads",
		"host_writes", "controller_busy_time", "power_cycles",
		"power_on_hours", "unsafe_shutdowns", "warning_temp_time",
		"critical_comp_time"}
	for _, id := range infoAttrs {
		if _, exists := results[id]; !exists {
			results[id] = SmartAttrThresholdResult{
				AttributeID: id,
				Status:      AttrStatusPassed,
			}
		}
	}

	return results, overallStatus
}

type NvmeHealthInput struct {
	CriticalWarning           int
	Temperature               int
	WarnCompTempThreshold     int
	CriticalCompTempThreshold int
	AvailableSpare            int
	AvailableSpareThreshold   int
	PercentageUsed            int
	MediaErrors               int
	NumErrLogEntries          int
}

func ComputeScsiAttributeStatuses(scsiInput *ScsiAttrInput) (map[string]SmartAttrThresholdResult, int) {
	attrs := []attrInput{
		{"scsi_grown_defect_list", scsiInput.GrownDefectList, 0},
		{"read_errors_corrected_by_eccfast", scsiInput.ReadErrorsCorrectedByEccFast, -1},
		{"read_errors_corrected_by_eccdelayed", scsiInput.ReadErrorsCorrectedByEccDelayed, -1},
		{"read_errors_corrected_by_rereads_rewrites", scsiInput.ReadErrorsCorrectedByRereads, 0},
		{"read_total_errors_corrected", scsiInput.ReadTotalErrorsCorrected, -1},
		{"read_correction_algorithm_invocations", scsiInput.ReadCorrectionAlgorithmInvocations, -1},
		{"read_total_uncorrected_errors", scsiInput.ReadTotalUncorrectedErrors, 0},
		{"write_errors_corrected_by_eccfast", scsiInput.WriteErrorsCorrectedByEccFast, -1},
		{"write_errors_corrected_by_eccdelayed", scsiInput.WriteErrorsCorrectedByEccDelayed, -1},
		{"write_errors_corrected_by_rereads_rewrites", scsiInput.WriteErrorsCorrectedByRereads, 0},
		{"write_total_errors_corrected", scsiInput.WriteTotalErrorsCorrected, -1},
		{"write_correction_algorithm_invocations", scsiInput.WriteCorrectionAlgorithmInvocations, -1},
		{"write_total_uncorrected_errors", scsiInput.WriteTotalUncorrectedErrors, 0},
	}

	meta := make(metadataLookup, len(ScsiMetadata))
	for k, v := range ScsiMetadata {
		meta[k] = attrMeta{Ideal: v.Ideal, Critical: v.Critical}
	}

	results, overallStatus := computeAttrResults(attrs, meta)
	return results, overallStatus
}

type attrInput struct {
	id        string
	value     int64
	threshold int64
}

type attrMeta struct {
	Ideal    string
	Critical bool
}

type metadataLookup map[string]attrMeta

func computeAttrResults(attrs []attrInput, meta metadataLookup) (map[string]SmartAttrThresholdResult, int) {
	results := make(map[string]SmartAttrThresholdResult)
	overallStatus := SMARTThresholdStatusPassed

	for _, attr := range attrs {
		if attr.threshold == -1 {
			results[attr.id] = SmartAttrThresholdResult{
				AttributeID: attr.id,
				Status:      AttrStatusPassed,
			}
			continue
		}

		info, ok := meta[attr.id]
		if !ok {
			results[attr.id] = SmartAttrThresholdResult{
				AttributeID: attr.id,
				Status:      AttrStatusPassed,
			}
			continue
		}

		failed := false
		if (info.Ideal == "low" && attr.value > attr.threshold) ||
			(info.Ideal == "high" && attr.value < attr.threshold) {
			failed = true
		}

		status := AttrStatusPassed
		reason := ""
		if failed {
			status = AttrStatusFailed
			reason = "Attribute is failing recommended SMART threshold"
		}

		results[attr.id] = SmartAttrThresholdResult{
			AttributeID:  attr.id,
			Status:       status,
			StatusReason: reason,
		}

		if failed {
			if info.Critical {
				overallStatus = SMARTThresholdStatusFailed
			} else if overallStatus == SMARTThresholdStatusPassed {
				overallStatus = SMARTThresholdStatusWarning
			}
		}
	}

	return results, overallStatus
}

type ScsiAttrInput struct {
	GrownDefectList                     int64
	ReadErrorsCorrectedByEccFast        int64
	ReadErrorsCorrectedByEccDelayed     int64
	ReadErrorsCorrectedByRereads        int64
	ReadTotalErrorsCorrected            int64
	ReadCorrectionAlgorithmInvocations  int64
	ReadTotalUncorrectedErrors          int64
	WriteErrorsCorrectedByEccFast       int64
	WriteErrorsCorrectedByEccDelayed    int64
	WriteErrorsCorrectedByRereads       int64
	WriteTotalErrorsCorrected           int64
	WriteCorrectionAlgorithmInvocations int64
	WriteTotalUncorrectedErrors         int64
}

func GenerateThresholdSummary(attrStatuses map[string]SmartAttrThresholdResult) string {
	if len(attrStatuses) == 0 {
		return ""
	}

	var failedAttrs, warningAttrs []string
	for id, result := range attrStatuses {
		displayName := id
		if result.Status == AttrStatusFailed {
			failedAttrs = append(failedAttrs, displayName)
		} else if result.Status == AttrStatusWarning {
			warningAttrs = append(warningAttrs, displayName)
		}
	}

	var parts []string
	if len(failedAttrs) > 0 {
		parts = append(parts, "Failed: "+strings.Join(failedAttrs, ", "))
	}
	if len(warningAttrs) > 0 {
		parts = append(parts, "Warning: "+strings.Join(warningAttrs, ", "))
	}
	return strings.Join(parts, "; ")
}
