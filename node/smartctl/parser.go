package smartctl

import (
	"crypto/md5"
	"encoding/json"
	"fmt"
	"regexp"
	"strconv"
	"strings"

	"github.com/unikii/dsentry/node/thresholds"
)

// ============================================
// 1. RAW JSON STRUCTURES (smartctl -a -j output)
// ============================================

type SmartctlOutput struct {
	JSONFormatVersion []int            `json:"json_format_version"`
	LocalTime         LocalTime        `json:"local_time"`
	Smartctl          SmartctlInfo     `json:"smartctl"`
	Device            DeviceInfo       `json:"device"`
	ModelFamily       string           `json:"model_family,omitempty"`
	ModelName         string           `json:"model_name"`
	SerialNumber      string           `json:"serial_number"`
	WWN               *WWNInfo         `json:"wwn,omitempty"`
	LogicalUnitID     string           `json:"logical_unit_id,omitempty"`
	FirmwareVersion   string           `json:"firmware_version"`
	UserCapacity      *UserCapacity    `json:"user_capacity,omitempty"`
	LogicalBlockSize  int64            `json:"logical_block_size,omitempty"`
	SMARTSupport      *SMARTSupport    `json:"smart_support,omitempty"`
	SMARTStatus       *SMARTStatus     `json:"smart_status,omitempty"`
	Temperature       *TemperatureInfo `json:"temperature,omitempty"`
	PowerOnTime       *PowerOnTimeInfo `json:"power_on_time,omitempty"`
	PowerCycleCount   *int             `json:"power_cycle_count,omitempty"`

	FormFactor   *FormFactorInfo `json:"form_factor,omitempty"`
	RotationRate *int            `json:"rotation_rate,omitempty"`

	ATASMARTAttributes *ATASMARTAttributes `json:"ata_smart_attributes,omitempty"`

	SCSIGrownDefectList      *int                      `json:"scsi_grown_defect_list,omitempty"`
	SCSIErrorCounters        *SCSIErrorCounters        `json:"scsi_error_counter_log,omitempty"`
	SCSIStartStop            *SCSIStartStop            `json:"scsi_start_stop_cycle_counter,omitempty"`
	SCSITemperature          *SCSITemperature          `json:"scsi_temperature,omitempty"`
	SCSIProtocolPort         *SCSIProtocolPort         `json:"scsi_protocol_specific_port,omitempty"`
	SCSISASPort0             *SCSISASPort              `json:"scsi_sas_port_0,omitempty"`
	SCSISASPort1             *SCSISASPort              `json:"scsi_sas_port_1,omitempty"`
	SCSIVendor               string                    `json:"scsi_vendor,omitempty"`
	SCSIProduct              string                    `json:"scsi_product,omitempty"`
	SCSIRevision             string                    `json:"scsi_revision,omitempty"`
	SCSIModelName            string                    `json:"scsi_model_name,omitempty"`
	SCSISerialNumber         string                    `json:"scsi_serial_number,omitempty"`
	SCSIEnvironmentalReports *SCSIEnvironmentalReports `json:"scsi_environmental_reports,omitempty"`

	NVMESMARTHealth          *NVMESMARTHealth            `json:"nvme_smart_health_information_log,omitempty"`
	NVMeTotalCapacity        *int64                      `json:"nvme_total_capacity,omitempty"`
	NVMeNamespaces           []NVMeNamespace             `json:"nvme_namespaces,omitempty"`
	NVMeMaxDataTransferPages *int                        `json:"nvme_maximum_data_transfer_pages,omitempty"`
	NVMeCompositeTempThresh  *NVMeCompositeTempThreshold `json:"nvme_composite_temperature_threshold,omitempty"`
	NVMePCIVendor            *NVMePCIVendorInfo          `json:"nvme_pci_vendor,omitempty"`
	NVMeIEEEOUIIdentifier    *int                        `json:"nvme_ieee_oui_identifier,omitempty"`

	NonMediumErrorCount  *int64 `json:"non_medium_error_count,omitempty"`
	SCSIPctUsedEndurance *int   `json:"scsi_percentage_used_endurance_indicator,omitempty"`
}

type NVMeCompositeTempThreshold struct {
	Warning  int `json:"warning"`
	Critical int `json:"critical"`
}

type NVMePCIVendorInfo struct {
	ID          int `json:"id"`
	SubsystemID int `json:"subsystem_id"`
}

type NVMeNamespace struct {
	ID   int          `json:"id"`
	Size UserCapacity `json:"size"`
}

func (o *SmartctlOutput) Normalize() {
	if o.ModelName == "" && o.SCSIModelName != "" {
		o.ModelName = o.SCSIModelName
	}
	if o.SerialNumber == "" && o.SCSISerialNumber != "" {
		o.SerialNumber = o.SCSISerialNumber
	}
	if o.UserCapacity == nil || o.UserCapacity.Bytes == 0 {
		if o.NVMeTotalCapacity != nil && *o.NVMeTotalCapacity > 0 {
			o.UserCapacity = &UserCapacity{Bytes: *o.NVMeTotalCapacity}
		} else if len(o.NVMeNamespaces) > 0 && o.NVMeNamespaces[0].Size.Bytes > 0 {
			o.UserCapacity = &UserCapacity{Bytes: o.NVMeNamespaces[0].Size.Bytes}
		}
	}
}

type SmartctlInfo struct {
	Version      []int    `json:"version"`
	SVNRevision  string   `json:"svn_revision"`
	PlatformInfo string   `json:"platform_info"`
	BuildInfo    string   `json:"build_info"`
	Argv         []string `json:"argv"`
	ExitStatus   int      `json:"exit_status"`
}

type DeviceInfo struct {
	Name     string `json:"name"`
	InfoName string `json:"info_name"`
	Type     string `json:"type"`
	Protocol string `json:"protocol"`
}

type WWNInfo struct {
	Naa int    `json:"naa"`
	Oui int    `json:"oui"`
	ID  uint64 `json:"id"`
}

type UserCapacity struct {
	Blocks int64 `json:"blocks"`
	Bytes  int64 `json:"bytes"`
}

type SMARTSupport struct {
	Enabled   bool `json:"enabled"`
	Available bool `json:"available"`
}

type SMARTStatus struct {
	Passed bool   `json:"passed"`
	String string `json:"string,omitempty"`
}

type TemperatureInfo struct {
	Current          int `json:"current"`
	DriveTrip        int `json:"drive_trip,omitempty"`
	DriveMax         int `json:"drive_max,omitempty"`
	OpLimitMax       int `json:"op_limit_max,omitempty"`
	CriticalLimitMax int `json:"critical_limit_max,omitempty"`
}

type PowerOnTimeInfo struct {
	Hours   int `json:"hours,omitempty"`
	Minutes int `json:"minutes,omitempty"`
}

type ATASMARTAttributes struct {
	Revision int                 `json:"revision"`
	Table    []ATASMARTAttribute `json:"table"`
}

type ATASMARTAttribute struct {
	ID         int    `json:"id"`
	Name       string `json:"name"`
	Value      int    `json:"value"`
	Worst      int    `json:"worst"`
	Thresh     int    `json:"thresh"`
	WhenFailed string `json:"when_failed"`
	Flags      struct {
		Value         int    `json:"value"`
		String        string `json:"string"`
		Prefailure    bool   `json:"prefailure"`
		UpdatedOnline bool   `json:"updated_online"`
		Performance   bool   `json:"performance"`
		ErrorRate     bool   `json:"error_rate"`
		EventCount    bool   `json:"event_count"`
		AutoKeep      bool   `json:"auto_keep"`
	} `json:"flags"`
	Raw struct {
		Value  int64  `json:"value"`
		String string `json:"string"`
	} `json:"raw"`
}

type NVMESMARTHealth struct {
	CriticalWarning                       int    `json:"critical_warning"`
	Temperature                           int    `json:"temperature"`
	AvailableSpare                        int    `json:"available_spare"`
	AvailableSpareThreshold               int    `json:"available_spare_threshold"`
	PercentageUsed                        int    `json:"percentage_used"`
	DataUnitsRead                         uint64 `json:"data_units_read"`
	DataUnitsWritten                      uint64 `json:"data_units_written"`
	HostReadCommands                      uint64 `json:"host_reads"`
	HostWriteCommands                     uint64 `json:"host_writes"`
	ControllerBusyTime                    uint64 `json:"controller_busy_time"`
	PowerCycles                           uint64 `json:"power_cycles"`
	PowerOnHours                          uint64 `json:"power_on_hours"`
	UnsafeShutdowns                       uint64 `json:"unsafe_shutdowns"`
	MediaAndDataIntegrityErrors           uint64 `json:"media_errors"`
	ErrorInformationLogEntries            uint64 `json:"num_err_log_entries"`
	WarningCompTemperatureTime            int    `json:"warning_temp_time"`
	CriticalCompTemperatureTime           int    `json:"critical_comp_time"`
	TemperatureSensors                    []int  `json:"temperature_sensors,omitempty"`
	ThermalManagementTemp1TransitionCount int    `json:"thermal_management_temp1_transition_count,omitempty"`
	ThermalManagementTemp2TransitionCount int    `json:"thermal_management_temp2_transition_count,omitempty"`
	ThermalManagementTemp1TotalTime       int    `json:"thermal_management_temp1_total_time,omitempty"`
	ThermalManagementTemp2TotalTime       int    `json:"thermal_management_temp2_total_time,omitempty"`
}

type SCSIErrorCounters struct {
	Read   *SCSIErrorCountersEntry `json:"read,omitempty"`
	Write  *SCSIErrorCountersEntry `json:"write,omitempty"`
	Verify *SCSIErrorCountersEntry `json:"verify,omitempty"`
}

type SCSIErrorCountersEntry struct {
	CorrectionAlgorithmInvocations   *uint64        `json:"correction_algorithm_invocations,omitempty"`
	ErrorsCorrectedByEccFast         *uint64        `json:"errors_corrected_by_eccfast,omitempty"`
	ErrorsCorrectedByEccDelayed      *uint64        `json:"errors_corrected_by_eccdelayed,omitempty"`
	ErrorsCorrectedByRereadsRewrites *uint64        `json:"errors_corrected_by_rereads_rewrites,omitempty"`
	TotalErrorsCorrected             *uint64        `json:"total_errors_corrected,omitempty"`
	TotalUncorrectedErrors           *uint64        `json:"total_uncorrected_errors,omitempty"`
	GigabytesProcessed               *SCSIGigabytes `json:"gigabytes_processed,omitempty"`
}

type SCSIGigabytes struct {
	Value float64 `json:"value"`
	Units string  `json:"units"`
}

func (g *SCSIGigabytes) UnmarshalJSON(data []byte) error {
	if len(data) == 0 || string(data) == "null" {
		return nil
	}
	if data[0] == '{' {
		type alias SCSIGigabytes
		return json.Unmarshal(data, (*alias)(g))
	}
	if data[0] == '"' {
		var s string
		if err := json.Unmarshal(data, &s); err != nil {
			return err
		}
		val, err := strconv.ParseFloat(s, 64)
		if err != nil {
			return err
		}
		g.Value = val
		g.Units = "GB"
		return nil
	}
	var val float64
	if err := json.Unmarshal(data, &val); err != nil {
		return err
	}
	g.Value = val
	g.Units = "GB"
	return nil
}

type FormFactorInfo struct {
	Name string
}

func (f *FormFactorInfo) UnmarshalJSON(data []byte) error {
	if len(data) == 0 || string(data) == "null" {
		return nil
	}
	if data[0] == '{' {
		var obj struct {
			AtaValue  int    `json:"ata_value"`
			Name      string `json:"name"`
			ScsiValue int    `json:"scsi_value"`
			String    string `json:"string"`
		}
		if err := json.Unmarshal(data, &obj); err != nil {
			return err
		}
		if obj.Name != "" {
			f.Name = obj.Name
		} else {
			f.Name = obj.String
		}
		return nil
	}
	var s string
	if err := json.Unmarshal(data, &s); err != nil {
		return err
	}
	f.Name = s
	return nil
}

type SCSIStartStop struct {
	YearOfManufacture                          string `json:"year_of_manufacture,omitempty"`
	WeekOfManufacture                          string `json:"week_of_manufacture,omitempty"`
	SpecifiedCycleCountOverDeviceLifetime      *int   `json:"specified_cycle_count_over_device_lifetime,omitempty"`
	AccumulatedStartStopCycles                 *int   `json:"accumulated_start_stop_cycles,omitempty"`
	SpecifiedLoadUnloadCountOverDeviceLifetime *int   `json:"specified_load_unload_count_over_device_lifetime,omitempty"`
	AccumulatedLoadUnloadCycles                *int   `json:"accumulated_load_unload_cycles,omitempty"`
}

type SCSIEnvironmentalReports struct {
	Temperature1 SCSITemperatureReport `json:"temperature_1"`
}

type SCSITemperatureReport struct {
	Current     int `json:"current"`
	LifetimeMax int `json:"lifetime_maximum"`
}

type SCSITemperature struct {
	Current   int `json:"current"`
	DriveTrip int `json:"drive_trip,omitempty"`
	Reference int `json:"reference,omitempty"`
}

type SCSIProtocolPort struct {
	LogicalUnitsServed struct {
		LUNInPort    int `json:"lun_in_port,omitempty"`
		NumberOfLuns int `json:"number_of_luns,omitempty"`
	} `json:"logical_units_served,omitempty"`
	RelativeTargetPortIdentifier uint16  `json:"relative_target_port_identifier,omitempty"`
	SASAddress                   string  `json:"sas_address,omitempty"`
	GDT                          int     `json:"gdt,omitempty"`
	PhyIdentifier                int     `json:"phy_identifier,omitempty"`
	InvalidDwordCount            *uint64 `json:"invalid_dword_count,omitempty"`
	RunningDisparityErrorCount   *uint64 `json:"running_disparity_error_count,omitempty"`
	LossOfDwordSyncCount         *uint64 `json:"loss_of_dword_sync_count,omitempty"`
	PhyResetProblemCount         *uint64 `json:"phy_reset_problem_count,omitempty"`
}

type SCSISASPhy struct {
	InvalidDwordCount          *uint64 `json:"invalid_dword_count,omitempty"`
	RunningDisparityErrorCount *uint64 `json:"running_disparity_error_count,omitempty"`
	LossOfDwordSyncCount       *uint64 `json:"loss_of_dword_synchronization_count,omitempty"`
	PhyResetProblemCount       *uint64 `json:"phy_reset_problem_count,omitempty"`
}

type SCSISASPort struct {
	Phy0 *SCSISASPhy `json:"phy_0,omitempty"`
}

type LocalTime struct {
	TimeT    int64  `json:"time_t"`
	Asctime  string `json:"asctime,omitempty"`
	Asctime2 string `json:"string,omitempty"`
}

func (lt *LocalTime) GetAsctime() string {
	if lt.Asctime != "" {
		return lt.Asctime
	}
	return lt.Asctime2
}

// ============================================
// 2. UNIFIED METRICS STRUCT (what we store)
// ============================================

type DeviceMeta struct {
	DeviceHash                      string  `json:"-"`
	DeviceName                      string  `json:"device_name"`
	SerialNumber                    string  `json:"serial_number"`
	ModelName                       string  `json:"model_name"`
	Vendor                          string  `json:"vendor"`
	Protocol                        string  `json:"protocol"`
	SMARTStatus                     int     `json:"smart_status"`           // 0=PASSED, 1=FAILED, 2=UNKNOWN/N/A
	SMARTThresholdStatus            int     `json:"smart_threshold_status"` // 0=PASSED, 1=WARNING, 2=FAILED (based on observed thresholds)
	SMARTEnabled                    bool    `json:"smart_enabled"`          // true if SMART is enabled (device reports it)
	SMARTAvailable                  bool    `json:"smart_available"`        // true if SMART is supported by the device
	TotalCapacityBytes              int64   `json:"total_capacity_bytes"`
	FirmwareVersion                 string  `json:"firmware_version"`
	WWN                             string  `json:"wwn"`
	ATAMinTemperatureCelsius        *int    `json:"ata_min_temperature_celsius,omitempty"`
	ATAMaxTemperatureCelsius        *int    `json:"ata_max_temperature_celsius,omitempty"`
	SSDTBWWarranty                  *int64  `json:"ssd_tbw_warranty,omitempty"`
	NVMEAvailableSpareThreshold     *int    `json:"nvme_available_spare_threshold,omitempty"`
	NVMEWarnCompTempThreshold       *int    `json:"nvme_warn_comp_temp_threshold,omitempty"`
	NVMECriticalCompTempThreshold   *int    `json:"nvme_critical_comp_temp_threshold,omitempty"`
	NVMEMaxDataTransferSize         *int    `json:"nvme_maximum_data_transfer_size,omitempty"`
	NVMePCIVendorID                 *string `json:"nvme_pci_vendor_id,omitempty"`
	NVMePCIVendorSubsystemID        *string `json:"nvme_pci_vendor_subsystem_id,omitempty"`
	NVMeIEEEOUIIdentifier           *string `json:"nvme_ieee_oui_identifier,omitempty"`
	HDDFormFactor                   *string `json:"hdd_form_factor,omitempty"`
	HDDRotationRate                 *int    `json:"hdd_rotation_rate,omitempty"`
	SCSIHDDSpecifiedCycleCount      *int    `json:"scsi_hdd_specified_cycle_count,omitempty"`
	SCSIHDDSpecifiedLoadUnloadCount *int    `json:"scsi_hdd_specified_load_unload_count,omitempty"`
	SCSIManufacturingDate           *string `json:"scsi_manufacturing_date,omitempty"`
	SCSIDriveTripTemperature        *int    `json:"scsi_drive_trip_temperature,omitempty"`
}

// DeviceMetrics is the wire format pushed to the hub. The JSON tags below
// ARE the contract with hub/api (schemas/metrics_schema.json references these
// exact names via its "go_field" entries). Any rename must bump
// MetricsSchemaVersion and update the schema on both sides in the same
// release.
type DeviceMetrics struct {
	DeviceHash string `json:"DeviceHash,omitempty"`

	// Universal metrics
	PowerOnHours        *int     `json:"PowerOnHours,omitempty"`
	PowerCycles         *int     `json:"PowerCycles,omitempty"`
	TemperatureCelsius  *int     `json:"TemperatureCelsius,omitempty"`
	TotalBytesWritten   *int64   `json:"TotalBytesWritten,omitempty"`
	TotalBytesRead      *int64   `json:"TotalBytesRead,omitempty"`
	WearLevelPct        *float64 `json:"WearLevelPct,omitempty"`
	AvailableSparePct   *int     `json:"AvailableSparePct,omitempty"`
	TransportErrorCount *int64   `json:"TransportErrorCount,omitempty"`
	UnsafeShutdownCount *int     `json:"UnsafeShutdownCount,omitempty"`

	// NVMe specific
	NVMECriticalWarning             *int   `json:"NVMECriticalWarning,omitempty"`
	NVMEHostReadCommands            *int64 `json:"NVMEHostReadCommands,omitempty"`
	NVMEHostWriteCommands           *int64 `json:"NVMEHostWriteCommands,omitempty"`
	NVMEControllerBusyTime          *int64 `json:"NVMEControllerBusyTime,omitempty"`
	NVMEMediaAndDataIntegrityErrors *int   `json:"NVMEMediaAndDataIntegrityErrors,omitempty"`
	NVMEErrorLogEntries             *int64 `json:"NVMEErrorLogEntries,omitempty"`
	NVMEWarningCompTempTime         *int   `json:"NVMEWarningCompTempTime,omitempty"`
	NVMECriticalCompTempTime        *int   `json:"NVMECriticalCompTempTime,omitempty"`
	NVMEThermalT1TransitionCount    *int   `json:"NVMEThermalT1TransitionCount,omitempty"`
	NVMEThermalT2TransitionCount    *int   `json:"NVMEThermalT2TransitionCount,omitempty"`

	// ATA metrics
	ATARawReadErrorRate     *int64 `json:"ATARawReadErrorRate,omitempty"`
	ATAReallocatedSectorCt  *int   `json:"ATAReallocatedSectorCt,omitempty"`
	ATASeekErrorRate        *int64 `json:"ATASeekErrorRate,omitempty"`
	ATAReportedUncorrect    *int   `json:"ATAReportedUncorrect,omitempty"`
	ATACommandTimeout       *int   `json:"ATACommandTimeout,omitempty"`
	ATACurrentPendingSector *int   `json:"ATACurrentPendingSector,omitempty"`
	ATAOfflineUncorrectable *int   `json:"ATAOfflineUncorrectable,omitempty"`

	// HDD metrics
	HDDStartStopCount     *int `json:"HDDStartStopCount,omitempty"`
	HDDLoadUnloadCycles   *int `json:"HDDLoadUnloadCycles,omitempty"`
	ATAHDDSpinRetryCount  *int `json:"ATAHDDSpinRetryCount,omitempty"`
	ATAHDDGSenseErrorRate *int `json:"ATAHDDGSenseErrorRate,omitempty"`

	// SCSI specific
	SCSIElementsInGrownDefectList *int `json:"SCSIElementsInGrownDefectList,omitempty"`
}

// ============================================
// 3. PROTOCOL PARSER INTERFACE
// ============================================

type ProtocolParser interface {
	ParseMeta(output *SmartctlOutput) (*DeviceMeta, error)
	ParseMetrics(output *SmartctlOutput) (*DeviceMetrics, error)
}

// ============================================
// 4. PROTOCOL DETECTION
// ============================================

func DetectProtocol(output *SmartctlOutput) (string, error) {
	protocol := strings.ToLower(output.Device.Protocol)
	deviceType := strings.ToLower(output.Device.Type)

	switch {
	case strings.Contains(protocol, "nvme"):
		return "nvme", nil
	case strings.Contains(protocol, "scsi") || strings.Contains(protocol, "sas"):
		if output.RotationRate != nil && *output.RotationRate > 0 {
			return "scsi_hdd", nil
		}
		if output.SCSIPctUsedEndurance != nil && *output.SCSIPctUsedEndurance >= 0 {
			return "scsi_ssd", nil
		}
		if strings.Contains(deviceType, "ssd") {
			return "scsi_ssd", nil
		}
		return "scsi_hdd", nil
	case strings.Contains(protocol, "ata") || strings.Contains(protocol, "sata"):
		if output.RotationRate != nil {
			if *output.RotationRate > 0 {
				return "ata_hdd", nil
			}
			return "ata_ssd", nil
		}
		if output.ATASMARTAttributes != nil {
			for _, attr := range output.ATASMARTAttributes.Table {
				if attr.Name == "Rotation_Rate" {
					if attr.Raw.Value > 0 {
						return "ata_hdd", nil
					}
					return "ata_ssd", nil
				}
			}
		}
		if strings.Contains(deviceType, "ssd") || strings.Contains(output.ModelName, "SSD") {
			return "ata_ssd", nil
		}
		return "ata_hdd", nil
	default:
		return "", fmt.Errorf("unknown protocol: %s", protocol)
	}
}

func GetParser(protocol string) (ProtocolParser, error) {
	switch protocol {
	case "nvme":
		return &NVMEParser{}, nil
	case "ata_ssd":
		return &ATASSDParser{}, nil
	case "ata_hdd":
		return &ATAHDDParser{}, nil
	case "scsi_hdd":
		return &SCSIHDDParser{}, nil
	case "scsi_ssd":
		return &SCSISSDParser{}, nil
	default:
		return nil, fmt.Errorf("unsupported protocol: %s", protocol)
	}
}

// ============================================
// 5. NVME PARSER
// ============================================

type NVMEParser struct{}

func (p *NVMEParser) ParseMeta(output *SmartctlOutput) (*DeviceMeta, error) {
	info := &DeviceMeta{
		SerialNumber:    output.SerialNumber,
		ModelName:       output.ModelName,
		Vendor:          "",
		Protocol:        "nvme",
		FirmwareVersion: output.FirmwareVersion,
	}

	if output.UserCapacity != nil {
		info.TotalCapacityBytes = output.UserCapacity.Bytes
	}

	info.SMARTStatus = ComputeSmartStatus(output)
	info.SMARTEnabled = output.SMARTSupport != nil && output.SMARTSupport.Enabled
	info.SMARTAvailable = output.SMARTSupport != nil && output.SMARTSupport.Available

	info.DeviceHash = generateDeviceHash(output, "")

	if output.WWN != nil {
		info.WWN = formatWWN(output.WWN)
	}

	health := output.NVMESMARTHealth
	if health != nil {
		spareThreshold := health.AvailableSpareThreshold
		info.NVMEAvailableSpareThreshold = &spareThreshold

		if health.PercentageUsed > 0 {
			totalWritten := int64(health.DataUnitsWritten) * 512000
			tbw := totalWritten * 100 / int64(health.PercentageUsed)
			info.SSDTBWWarranty = &tbw
		}
	}

	if output.NVMeMaxDataTransferPages != nil {
		// smartctl reports the NVMe MDTS in units of the minimum memory page
		// size (4 KiB); the hub/UI treat this field as bytes.
		size := *output.NVMeMaxDataTransferPages * 4096
		info.NVMEMaxDataTransferSize = &size
	}
	if output.NVMeCompositeTempThresh != nil {
		warn := output.NVMeCompositeTempThresh.Warning
		crit := output.NVMeCompositeTempThresh.Critical
		info.NVMEWarnCompTempThreshold = &warn
		info.NVMECriticalCompTempThreshold = &crit
	}

	if output.NVMePCIVendor != nil {
		vendorID := fmt.Sprintf("0x%04X", output.NVMePCIVendor.ID)
		subsysID := fmt.Sprintf("0x%04X", output.NVMePCIVendor.SubsystemID)
		info.NVMePCIVendorID = &vendorID
		info.NVMePCIVendorSubsystemID = &subsysID
	}
	if output.NVMeIEEEOUIIdentifier != nil {
		oui := fmt.Sprintf("0x%06X", *output.NVMeIEEEOUIIdentifier)
		info.NVMeIEEEOUIIdentifier = &oui
	}

	return info, nil
}

func (p *NVMEParser) ParseMetrics(output *SmartctlOutput) (*DeviceMetrics, error) {
	health := output.NVMESMARTHealth
	if health == nil {
		return nil, fmt.Errorf("no NVMe health data found")
	}

	metrics := &DeviceMetrics{
		DeviceHash: generateDeviceHash(output, ""),
	}

	// Universal metrics
	powerOnHours := int(health.PowerOnHours)
	metrics.PowerOnHours = &powerOnHours

	powerCycles := int(health.PowerCycles)
	metrics.PowerCycles = &powerCycles

	temp := health.Temperature
	metrics.TemperatureCelsius = &temp

	totalWritten := int64(health.DataUnitsWritten) * 512000 // Convert to bytes
	metrics.TotalBytesWritten = &totalWritten

	totalRead := int64(health.DataUnitsRead) * 512000
	metrics.TotalBytesRead = &totalRead

	wearLevel := float64(health.PercentageUsed)
	metrics.WearLevelPct = &wearLevel

	availableSpare := health.AvailableSpare
	metrics.AvailableSparePct = &availableSpare

	unsafeShutdowns := int(health.UnsafeShutdowns)
	metrics.UnsafeShutdownCount = &unsafeShutdowns

	// NVMe specific
	criticalWarning := health.CriticalWarning
	metrics.NVMECriticalWarning = &criticalWarning

	hostReadCmds := int64(health.HostReadCommands)
	metrics.NVMEHostReadCommands = &hostReadCmds

	hostWriteCmds := int64(health.HostWriteCommands)
	metrics.NVMEHostWriteCommands = &hostWriteCmds

	busyTime := int64(health.ControllerBusyTime)
	metrics.NVMEControllerBusyTime = &busyTime

	mediaErrors := int(health.MediaAndDataIntegrityErrors)
	metrics.NVMEMediaAndDataIntegrityErrors = &mediaErrors

	errorLogEntries := int64(health.ErrorInformationLogEntries)
	metrics.NVMEErrorLogEntries = &errorLogEntries

	warningTempTime := health.WarningCompTemperatureTime
	metrics.NVMEWarningCompTempTime = &warningTempTime

	criticalTempTime := health.CriticalCompTemperatureTime
	metrics.NVMECriticalCompTempTime = &criticalTempTime

	t1Transition := health.ThermalManagementTemp1TransitionCount
	metrics.NVMEThermalT1TransitionCount = &t1Transition

	t2Transition := health.ThermalManagementTemp2TransitionCount
	metrics.NVMEThermalT2TransitionCount = &t2Transition

	return metrics, nil
}

// ============================================
// 6. SATA SSD PARSER
// ============================================

type ATASSDParser struct{}

// parseATABaseMeta builds the metadata shared by SATA SSD and HDD parsers.
func parseATABaseMeta(output *SmartctlOutput, protocol string) *DeviceMeta {
	info := &DeviceMeta{
		SerialNumber:    output.SerialNumber,
		ModelName:       output.ModelName,
		Vendor:          "",
		Protocol:        protocol,
		FirmwareVersion: output.FirmwareVersion,
	}

	if output.UserCapacity != nil {
		info.TotalCapacityBytes = output.UserCapacity.Bytes
	}

	info.DeviceHash = generateDeviceHash(output, "")

	if output.WWN != nil {
		info.WWN = formatWWN(output.WWN)
	}

	info.SMARTStatus = ComputeSmartStatus(output)
	info.SMARTEnabled = output.SMARTSupport != nil && output.SMARTSupport.Enabled
	info.SMARTAvailable = output.SMARTSupport != nil && output.SMARTSupport.Available

	return info
}

func ataAttributes(output *SmartctlOutput) map[int]*ATASMARTAttribute {
	if output.ATASMARTAttributes == nil {
		return nil
	}
	return buildAttributeMap(output.ATASMARTAttributes.Table)
}

func (p *ATASSDParser) ParseMeta(output *SmartctlOutput) (*DeviceMeta, error) {
	info := parseATABaseMeta(output, "ata_ssd")
	info.SSDTBWWarranty = estimateSSDTBWWarranty(output)
	extractATATempMinMax(ataAttributes(output), info)
	return info, nil
}

func extractTemperatureFromAttr(v *ATASMARTAttribute) int {
	rawStr := strings.TrimSpace(v.Raw.String)
	if idx := strings.IndexByte(rawStr, ' '); idx > 0 {
		if parsed, err := strconv.Atoi(rawStr[:idx]); err == nil && parsed > 0 && parsed <= 100 {
			return parsed
		}
	}
	if rawVal, err := strconv.Atoi(rawStr); err == nil && rawVal > 0 && rawVal <= 100 {
		return rawVal
	}
	if v.Value > 0 && v.Value <= 100 {
		return v.Value
	}
	if v.Raw.Value > 0 && v.Raw.Value <= 100 {
		return int(v.Raw.Value)
	}
	return 0
}

func (p *ATASSDParser) ParseMetrics(output *SmartctlOutput) (*DeviceMetrics, error) {
	if output.ATASMARTAttributes == nil {
		return nil, fmt.Errorf("no ATA SMART attributes found")
	}

	attrs := buildAttributeMap(output.ATASMARTAttributes.Table)
	metrics := &DeviceMetrics{
		DeviceHash: generateDeviceHash(output, ""),
	}

	parseUniversalATAMetrics(metrics, attrs, output)
	return metrics, nil
}

// ============================================
// 7. SATA HDD PARSER
// ============================================

type ATAHDDParser struct{}

func (p *ATAHDDParser) ParseMeta(output *SmartctlOutput) (*DeviceMeta, error) {
	info := parseATABaseMeta(output, "ata_hdd")

	attrs := ataAttributes(output)
	if output.RotationRate != nil {
		info.HDDRotationRate = output.RotationRate
	} else if v := attrs[217]; v != nil && v.Name == "Rotation_Rate" {
		rotation := int(v.Raw.Value)
		info.HDDRotationRate = &rotation
	}
	if output.FormFactor != nil {
		ff := output.FormFactor.Name
		info.HDDFormFactor = &ff
	}

	extractATATempMinMax(attrs, info)

	return info, nil
}

func (p *ATAHDDParser) ParseMetrics(output *SmartctlOutput) (*DeviceMetrics, error) {
	if output.ATASMARTAttributes == nil {
		return nil, fmt.Errorf("no ATA SMART attributes found")
	}

	attrs := buildAttributeMap(output.ATASMARTAttributes.Table)
	metrics := &DeviceMetrics{
		DeviceHash: generateDeviceHash(output, ""),
	}

	// Same universal metrics parsing as SSD...
	parseUniversalATAMetrics(metrics, attrs, output)

	// HDD specific metrics
	if v := attrs[4]; v != nil {
		startStop := int(v.Raw.Value)
		metrics.HDDStartStopCount = &startStop
	}
	if v := attrs[193]; v != nil {
		loadUnload := int(v.Raw.Value)
		metrics.HDDLoadUnloadCycles = &loadUnload
	}
	if v := attrs[10]; v != nil {
		spinRetry := int(v.Raw.Value)
		metrics.ATAHDDSpinRetryCount = &spinRetry
	}
	if v := attrs[191]; v != nil {
		gSense := int(v.Raw.Value)
		metrics.ATAHDDGSenseErrorRate = &gSense
	}

	return metrics, nil
}

func parseUniversalATAMetrics(metrics *DeviceMetrics, attrs map[int]*ATASMARTAttribute, output *SmartctlOutput) {
	if v := attrs[9]; v != nil {
		hours := int(v.Raw.Value)
		metrics.PowerOnHours = &hours
	}

	if v := attrs[12]; v != nil {
		cycles := int(v.Raw.Value)
		metrics.PowerCycles = &cycles
	}

	if v := attrs[194]; v != nil {
		temp := extractTemperatureFromAttr(v)
		if temp > 0 {
			metrics.TemperatureCelsius = &temp
		}
	} else if v := attrs[190]; v != nil {
		temp := extractTemperatureFromAttr(v)
		if temp > 0 {
			metrics.TemperatureCelsius = &temp
		}
	}
	if metrics.TemperatureCelsius == nil && output.Temperature != nil {
		temp := output.Temperature.Current
		if temp > 0 && temp <= 100 {
			metrics.TemperatureCelsius = &temp
		}
	}

	if v := attrs[241]; v != nil {
		written := v.Raw.Value * ataBytesPerLBA(output)
		metrics.TotalBytesWritten = &written
	} else if v := attrs[175]; v != nil && isHostWriteCounter(v) {
		written := v.Raw.Value * 1024 * 1024
		metrics.TotalBytesWritten = &written
	}

	if v := attrs[242]; v != nil {
		read := v.Raw.Value * ataBytesPerLBA(output)
		metrics.TotalBytesRead = &read
	} else if v := attrs[174]; v != nil && isHostReadCounter(v) {
		read := v.Raw.Value * 1024 * 1024
		metrics.TotalBytesRead = &read
	}

	if v := attrs[177]; v != nil {
		wear := 100.0 - float64(v.Value)
		if v.Value <= 100 {
			metrics.WearLevelPct = &wear
		}
	} else if v := attrs[233]; v != nil {
		wear := 100.0 - float64(v.Value)
		if v.Value <= 100 {
			metrics.WearLevelPct = &wear
		}
	} else if v := attrs[173]; v != nil {
		wear := 100.0 - float64(v.Value)
		if v.Value <= 100 {
			metrics.WearLevelPct = &wear
		}
	}

	if v := attrs[232]; v != nil {
		spare := int(v.Value)
		metrics.AvailableSparePct = &spare
	}

	if v := attrs[199]; v != nil {
		errors := v.Raw.Value
		metrics.TransportErrorCount = &errors
	}

	if v := attrs[192]; v != nil {
		shutdowns := int(v.Raw.Value)
		metrics.UnsafeShutdownCount = &shutdowns
	} else if v := attrs[174]; v != nil && v.Name == "Power-Off_Retract_Count" {
		shutdowns := int(v.Raw.Value)
		metrics.UnsafeShutdownCount = &shutdowns
	}

	if v := attrs[1]; v != nil {
		metrics.ATARawReadErrorRate = &v.Raw.Value
	}
	if v := attrs[5]; v != nil {
		realloc := int(v.Raw.Value)
		metrics.ATAReallocatedSectorCt = &realloc
	}
	if v := attrs[7]; v != nil {
		metrics.ATASeekErrorRate = &v.Raw.Value
	}
	if v := attrs[187]; v != nil {
		uncorrect := int(v.Raw.Value)
		metrics.ATAReportedUncorrect = &uncorrect
	}
	if v := attrs[188]; v != nil {
		timeout := int(v.Raw.Value)
		metrics.ATACommandTimeout = &timeout
	}
	if v := attrs[197]; v != nil {
		pending := int(v.Raw.Value)
		metrics.ATACurrentPendingSector = &pending
	}
	if v := attrs[198]; v != nil {
		offline := int(v.Raw.Value)
		metrics.ATAOfflineUncorrectable = &offline
	}
}

// ============================================
// 8. SCSI PARSERS (HDD & SSD)
// ============================================

func parseSCSIBaseStaticInfo(output *SmartctlOutput, protocol string) *DeviceMeta {
	info := &DeviceMeta{
		SerialNumber:    output.SerialNumber,
		ModelName:       output.ModelName,
		Vendor:          output.SCSIVendor,
		Protocol:        protocol,
		FirmwareVersion: output.FirmwareVersion,
	}

	if output.UserCapacity != nil {
		info.TotalCapacityBytes = output.UserCapacity.Bytes
	}

	info.DeviceHash = generateDeviceHash(output, "")

	if output.WWN != nil {
		info.WWN = formatWWN(output.WWN)
	} else if output.LogicalUnitID != "" {
		info.WWN = output.LogicalUnitID
	}

	info.SMARTStatus = ComputeSmartStatus(output)
	info.SMARTEnabled = output.SMARTSupport != nil && output.SMARTSupport.Enabled
	info.SMARTAvailable = output.SMARTSupport != nil && output.SMARTSupport.Available

	if output.SCSIStartStop != nil {
		if output.SCSIStartStop.YearOfManufacture != "" && output.SCSIStartStop.WeekOfManufacture != "" {
			dateStr := output.SCSIStartStop.YearOfManufacture + "-W" + output.SCSIStartStop.WeekOfManufacture
			info.SCSIManufacturingDate = &dateStr
		}
	}

	if output.SCSITemperature != nil {
		tripTemp := output.SCSITemperature.DriveTrip
		info.SCSIDriveTripTemperature = &tripTemp
	} else if output.Temperature != nil && output.Temperature.DriveTrip > 0 {
		tripTemp := output.Temperature.DriveTrip
		info.SCSIDriveTripTemperature = &tripTemp
	}

	return info
}

func parseSCSIMetrics(metrics *DeviceMetrics, output *SmartctlOutput) {
	if output.PowerOnTime != nil {
		if output.PowerOnTime.Hours > 0 {
			metrics.PowerOnHours = &output.PowerOnTime.Hours
		} else if output.PowerOnTime.Minutes > 0 {
			hours := output.PowerOnTime.Minutes / 60
			if hours == 0 {
				hours = 1
			}
			metrics.PowerOnHours = &hours
		}
	}

	if output.SCSIStartStop != nil && output.SCSIStartStop.AccumulatedStartStopCycles != nil {
		metrics.PowerCycles = output.SCSIStartStop.AccumulatedStartStopCycles
	}

	if output.SCSIEnvironmentalReports != nil {
		temp := output.SCSIEnvironmentalReports.Temperature1.Current
		if temp > 0 {
			metrics.TemperatureCelsius = &temp
		}
	} else if output.SCSITemperature != nil {
		temp := output.SCSITemperature.Current
		metrics.TemperatureCelsius = &temp
	} else if output.Temperature != nil {
		temp := output.Temperature.Current
		metrics.TemperatureCelsius = &temp
	}

	if output.SCSIErrorCounters != nil {
		if output.SCSIErrorCounters.Read != nil && output.SCSIErrorCounters.Read.GigabytesProcessed != nil {
			readGB := output.SCSIErrorCounters.Read.GigabytesProcessed.Value
			readBytes := int64(readGB * 1_000_000_000)
			metrics.TotalBytesRead = &readBytes
		}
		if output.SCSIErrorCounters.Write != nil && output.SCSIErrorCounters.Write.GigabytesProcessed != nil {
			writeGB := output.SCSIErrorCounters.Write.GigabytesProcessed.Value
			writeBytes := int64(writeGB * 1_000_000_000)
			metrics.TotalBytesWritten = &writeBytes
		}
	}

	if output.NonMediumErrorCount != nil {
		transportErrors := *output.NonMediumErrorCount
		metrics.TransportErrorCount = &transportErrors
	}

	if output.SCSIProtocolPort != nil {
		addTransportErrors(metrics, output.SCSIProtocolPort.InvalidDwordCount)
	}
	for _, port := range []*SCSISASPort{output.SCSISASPort0, output.SCSISASPort1} {
		if port == nil || port.Phy0 == nil {
			continue
		}
		addTransportErrors(metrics, port.Phy0.InvalidDwordCount)
		addTransportErrors(metrics, port.Phy0.RunningDisparityErrorCount)
		addTransportErrors(metrics, port.Phy0.LossOfDwordSyncCount)
		addTransportErrors(metrics, port.Phy0.PhyResetProblemCount)
	}
}

func addTransportErrors(metrics *DeviceMetrics, count *uint64) {
	if count == nil {
		return
	}
	if metrics.TransportErrorCount == nil {
		zero := int64(0)
		metrics.TransportErrorCount = &zero
	}
	*metrics.TransportErrorCount += int64(*count)
}

type SCSIHDDParser struct{}

func (p *SCSIHDDParser) ParseMeta(output *SmartctlOutput) (*DeviceMeta, error) {
	info := parseSCSIBaseStaticInfo(output, "scsi_hdd")

	if output.SCSIStartStop != nil {
		info.SCSIHDDSpecifiedCycleCount = output.SCSIStartStop.SpecifiedCycleCountOverDeviceLifetime
		info.SCSIHDDSpecifiedLoadUnloadCount = output.SCSIStartStop.SpecifiedLoadUnloadCountOverDeviceLifetime
	}

	if output.FormFactor != nil {
		ff := output.FormFactor.Name
		info.HDDFormFactor = &ff
	}
	if output.RotationRate != nil {
		info.HDDRotationRate = output.RotationRate
	}

	return info, nil
}

func (p *SCSIHDDParser) ParseMetrics(output *SmartctlOutput) (*DeviceMetrics, error) {
	metrics := &DeviceMetrics{
		DeviceHash: generateDeviceHash(output, ""),
	}

	parseSCSIMetrics(metrics, output)

	if output.SCSIStartStop != nil {
		if output.SCSIStartStop.AccumulatedLoadUnloadCycles != nil {
			metrics.HDDLoadUnloadCycles = output.SCSIStartStop.AccumulatedLoadUnloadCycles
		}
	}

	if output.SCSIGrownDefectList != nil {
		metrics.SCSIElementsInGrownDefectList = output.SCSIGrownDefectList
	}

	return metrics, nil
}

type SCSISSDParser struct{}

func (p *SCSISSDParser) ParseMeta(output *SmartctlOutput) (*DeviceMeta, error) {
	info := parseSCSIBaseStaticInfo(output, "scsi_ssd")
	// Estimate the rated TBW from the endurance indicator and the bytes the
	// drive reports having written (same approach as the ATA/NVMe parsers).
	info.SSDTBWWarranty = estimateSCSISSDBW(output)
	return info, nil
}

// estimateSCSISSDBW estimates the drive's rated total bytes written from the
// used-endurance percentage and the cumulative host writes reported by the
// SCSI error counters. It returns nil when either signal is unavailable.
func estimateSCSISSDBW(output *SmartctlOutput) *int64 {
	if output.SCSIPctUsedEndurance == nil {
		return nil
	}
	wearPct := float64(*output.SCSIPctUsedEndurance)
	if wearPct <= 0 || wearPct > 100 {
		return nil
	}
	if output.SCSIErrorCounters == nil || output.SCSIErrorCounters.Write == nil ||
		output.SCSIErrorCounters.Write.GigabytesProcessed == nil {
		return nil
	}
	writtenGB := output.SCSIErrorCounters.Write.GigabytesProcessed.Value
	if writtenGB <= 0 {
		return nil
	}
	totalWritten := int64(writtenGB * 1_000_000_000)
	tbw := int64(float64(totalWritten) / (wearPct / 100.0))
	return &tbw
}

func (p *SCSISSDParser) ParseMetrics(output *SmartctlOutput) (*DeviceMetrics, error) {
	metrics := &DeviceMetrics{
		DeviceHash: generateDeviceHash(output, ""),
	}

	parseSCSIMetrics(metrics, output)

	if output.SCSIPctUsedEndurance != nil {
		wear := float64(*output.SCSIPctUsedEndurance)
		metrics.WearLevelPct = &wear
	}

	return metrics, nil
}

// ============================================
// 9. HELPER FUNCTIONS
// ============================================

func buildAttributeMap(table []ATASMARTAttribute) map[int]*ATASMARTAttribute {
	attrs := make(map[int]*ATASMARTAttribute)
	for i := range table {
		attrs[table[i].ID] = &table[i]
	}
	return attrs
}

// isHostWriteCounter reports whether an ATA attribute is a host-written
// byte counter. Attributes 174/175 are vendor-specific and must not be
// treated as write counters unless the drive actually names them so.
func isHostWriteCounter(v *ATASMARTAttribute) bool {
	n := v.Name
	return strings.Contains(n, "Host_Writes") || strings.Contains(n, "Writes_MiB") ||
		strings.Contains(n, "Total_LBAs_Written") || strings.Contains(n, "Lifetime_Writes")
}

func isHostReadCounter(v *ATASMARTAttribute) bool {
	n := v.Name
	return strings.Contains(n, "Host_Reads") || strings.Contains(n, "Reads_MiB") ||
		strings.Contains(n, "Total_LBAs_Read") || strings.Contains(n, "Lifetime_Reads")
}

func generateDeviceHash(output *SmartctlOutput, wwnFallback string) string {
	identity := output.SerialNumber
	if identity == "" || identity == "000000000000" {
		if output.WWN != nil {
			identity = formatWWN(output.WWN)
		} else if wwnFallback != "" {
			identity = wwnFallback
		} else if output.LogicalUnitID != "" {
			identity = output.LogicalUnitID
		}
	}
	if identity == "" {
		identity = "unknown"
	}
	model := output.ModelName
	input := fmt.Sprintf("%s|%s", identity, model)
	hash := md5.Sum([]byte(input))
	return fmt.Sprintf("%x", hash)
}

func ComputeDeviceHash(output *SmartctlOutput, wwnFallback string) string {
	return generateDeviceHash(output, wwnFallback)
}

func formatWWN(wwn *WWNInfo) string {
	if wwn == nil {
		return ""
	}
	fullWWN := (uint64(wwn.Naa) << 60) | (uint64(wwn.Oui) << 36) | wwn.ID
	return fmt.Sprintf("0x%016x", fullWWN)
}

func ataBytesPerLBA(output *SmartctlOutput) int64 {
	if output != nil && output.LogicalBlockSize > 0 {
		return output.LogicalBlockSize
	}
	return 512
}

func estimateSSDTBWWarranty(output *SmartctlOutput) *int64 {
	if output.ATASMARTAttributes == nil {
		return nil
	}
	attrs := buildAttributeMap(output.ATASMARTAttributes.Table)

	var totalWritten int64
	if v := attrs[241]; v != nil {
		totalWritten = v.Raw.Value * ataBytesPerLBA(output)
	} else if v := attrs[175]; v != nil && isHostWriteCounter(v) {
		totalWritten = v.Raw.Value * 1024 * 1024
	}

	var wearPct float64
	if v := attrs[177]; v != nil && v.Value > 0 && v.Value <= 100 {
		wearPct = 100.0 - float64(v.Value)
	} else if v := attrs[233]; v != nil && v.Value > 0 && v.Value <= 100 {
		wearPct = 100.0 - float64(v.Value)
	} else if v := attrs[173]; v != nil && v.Value > 0 && v.Value <= 100 {
		wearPct = 100.0 - float64(v.Value)
	}

	if totalWritten > 0 && wearPct > 0 {
		tbw := int64(float64(totalWritten) / (wearPct / 100.0))
		return &tbw
	}
	return nil
}

var tempMinMaxRe = regexp.MustCompile(`Min/Max\s+(\d+)/(\d+)`)

func extractATATempMinMax(attrs map[int]*ATASMARTAttribute, info *DeviceMeta) {
	if info.ATAMinTemperatureCelsius != nil && info.ATAMaxTemperatureCelsius != nil {
		return
	}
	var rawStr string
	if v := attrs[194]; v != nil {
		rawStr = v.Raw.String
	} else if v := attrs[190]; v != nil {
		rawStr = v.Raw.String
	}
	if rawStr == "" {
		return
	}
	matches := tempMinMaxRe.FindStringSubmatch(rawStr)
	if len(matches) == 3 {
		if min, err := strconv.Atoi(matches[1]); err == nil {
			info.ATAMinTemperatureCelsius = &min
		}
		if max, err := strconv.Atoi(matches[2]); err == nil {
			info.ATAMaxTemperatureCelsius = &max
		}
	}
}

func ComputeMetaHash(meta *DeviceMeta) string {
	metaCopy := *meta
	metaCopy.DeviceHash = ""
	metaCopy.SSDTBWWarranty = nil
	data, err := json.Marshal(metaCopy)
	if err != nil {
		return ""
	}
	hash := md5.Sum(data)
	return fmt.Sprintf("%x", hash)
}

func ComputeThresholdStatuses(output *SmartctlOutput, protocol string) (map[string]thresholds.SmartAttrThresholdResult, int) {
	switch {
	case strings.HasPrefix(protocol, "ata"):
		return computeAtaThresholds(output)
	case protocol == "nvme":
		return computeNvmeThresholds(output)
	case strings.HasPrefix(protocol, "scsi"):
		return computeScsiThresholds(output)
	default:
		return nil, thresholds.SMARTThresholdStatusPassed
	}
}

func computeAtaThresholds(output *SmartctlOutput) (map[string]thresholds.SmartAttrThresholdResult, int) {
	if output.ATASMARTAttributes == nil {
		return nil, thresholds.SMARTThresholdStatusPassed
	}

	attrMap := buildAttributeMap(output.ATASMARTAttributes.Table)
	inputs := make(map[int]*thresholds.AtaAttrInput)

	for id, attr := range attrMap {
		input := &thresholds.AtaAttrInput{
			Value:      attr.Value,
			RawValue:   attr.Raw.Value,
			RawString:  attr.Raw.String,
			WhenFailed: attr.WhenFailed,
		}

		inputs[id] = input
	}

	thresholds.PrepareAtaTransformedValues(inputs)

	return thresholds.ComputeAtaAttributeStatuses(inputs)
}

func computeNvmeThresholds(output *SmartctlOutput) (map[string]thresholds.SmartAttrThresholdResult, int) {
	if output.NVMESMARTHealth == nil {
		return nil, thresholds.SMARTThresholdStatusPassed
	}

	health := output.NVMESMARTHealth
	warnTemp, critTemp := 0, 0
	if output.NVMeCompositeTempThresh != nil {
		warnTemp = output.NVMeCompositeTempThresh.Warning
		critTemp = output.NVMeCompositeTempThresh.Critical
	} else if output.Temperature != nil {
		warnTemp = output.Temperature.OpLimitMax
		critTemp = output.Temperature.CriticalLimitMax
	}
	input := &thresholds.NvmeHealthInput{
		CriticalWarning:           health.CriticalWarning,
		Temperature:               health.Temperature,
		WarnCompTempThreshold:     warnTemp,
		CriticalCompTempThreshold: critTemp,
		AvailableSpare:            health.AvailableSpare,
		AvailableSpareThreshold:   health.AvailableSpareThreshold,
		PercentageUsed:            health.PercentageUsed,
		MediaErrors:               int(health.MediaAndDataIntegrityErrors),
		NumErrLogEntries:          int(health.ErrorInformationLogEntries),
	}

	return thresholds.ComputeNvmeAttributeStatuses(input)
}

func computeScsiThresholds(output *SmartctlOutput) (map[string]thresholds.SmartAttrThresholdResult, int) {
	input := &thresholds.ScsiAttrInput{}

	if output.SCSIGrownDefectList != nil {
		input.GrownDefectList = int64(*output.SCSIGrownDefectList)
	}

	if output.SCSIErrorCounters != nil {
		if output.SCSIErrorCounters.Read != nil {
			if output.SCSIErrorCounters.Read.ErrorsCorrectedByEccFast != nil {
				input.ReadErrorsCorrectedByEccFast = int64(*output.SCSIErrorCounters.Read.ErrorsCorrectedByEccFast)
			}
			if output.SCSIErrorCounters.Read.ErrorsCorrectedByEccDelayed != nil {
				input.ReadErrorsCorrectedByEccDelayed = int64(*output.SCSIErrorCounters.Read.ErrorsCorrectedByEccDelayed)
			}
			if output.SCSIErrorCounters.Read.ErrorsCorrectedByRereadsRewrites != nil {
				input.ReadErrorsCorrectedByRereads = int64(*output.SCSIErrorCounters.Read.ErrorsCorrectedByRereadsRewrites)
			}
			if output.SCSIErrorCounters.Read.TotalErrorsCorrected != nil {
				input.ReadTotalErrorsCorrected = int64(*output.SCSIErrorCounters.Read.TotalErrorsCorrected)
			}
			if output.SCSIErrorCounters.Read.CorrectionAlgorithmInvocations != nil {
				input.ReadCorrectionAlgorithmInvocations = int64(*output.SCSIErrorCounters.Read.CorrectionAlgorithmInvocations)
			}
			if output.SCSIErrorCounters.Read.TotalUncorrectedErrors != nil {
				input.ReadTotalUncorrectedErrors = int64(*output.SCSIErrorCounters.Read.TotalUncorrectedErrors)
			}
		}
		if output.SCSIErrorCounters.Write != nil {
			if output.SCSIErrorCounters.Write.ErrorsCorrectedByEccFast != nil {
				input.WriteErrorsCorrectedByEccFast = int64(*output.SCSIErrorCounters.Write.ErrorsCorrectedByEccFast)
			}
			if output.SCSIErrorCounters.Write.ErrorsCorrectedByEccDelayed != nil {
				input.WriteErrorsCorrectedByEccDelayed = int64(*output.SCSIErrorCounters.Write.ErrorsCorrectedByEccDelayed)
			}
			if output.SCSIErrorCounters.Write.ErrorsCorrectedByRereadsRewrites != nil {
				input.WriteErrorsCorrectedByRereads = int64(*output.SCSIErrorCounters.Write.ErrorsCorrectedByRereadsRewrites)
			}
			if output.SCSIErrorCounters.Write.TotalErrorsCorrected != nil {
				input.WriteTotalErrorsCorrected = int64(*output.SCSIErrorCounters.Write.TotalErrorsCorrected)
			}
			if output.SCSIErrorCounters.Write.CorrectionAlgorithmInvocations != nil {
				input.WriteCorrectionAlgorithmInvocations = int64(*output.SCSIErrorCounters.Write.CorrectionAlgorithmInvocations)
			}
			if output.SCSIErrorCounters.Write.TotalUncorrectedErrors != nil {
				input.WriteTotalUncorrectedErrors = int64(*output.SCSIErrorCounters.Write.TotalUncorrectedErrors)
			}
		}
	}

	return thresholds.ComputeScsiAttributeStatuses(input)
}
