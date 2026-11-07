package smartctl

import "testing"

func TestComputeMetaHashIncludesHealthStatus(t *testing.T) {
	meta := &DeviceMeta{
		DeviceHash:           "device",
		ModelName:            "model",
		SMARTStatus:          0,
		SMARTThresholdStatus: 0,
	}
	passed := ComputeMetaHash(meta)

	meta.SMARTThresholdStatus = 1
	warning := ComputeMetaHash(meta)
	if passed == warning {
		t.Fatal("threshold status change did not change metadata hash")
	}

	meta.SMARTThresholdStatus = 0
	meta.SMARTStatus = 1
	failed := ComputeMetaHash(meta)
	if passed == failed {
		t.Fatal("SMART status change did not change metadata hash")
	}
}

func TestATABytesPerLBAUsesLogicalBlockSize(t *testing.T) {
	if got := ataBytesPerLBA(&SmartctlOutput{LogicalBlockSize: 4096}); got != 4096 {
		t.Fatalf("expected 4096, got %d", got)
	}
	if got := ataBytesPerLBA(&SmartctlOutput{}); got != 512 {
		t.Fatalf("expected 512 fallback, got %d", got)
	}
}

func TestComputeDeviceHashUsesFallbackIdentity(t *testing.T) {
	output := &SmartctlOutput{ModelName: "same model"}
	first := ComputeDeviceHash(output, "/dev/disk1")
	second := ComputeDeviceHash(output, "/dev/disk2")
	if first == second {
		t.Fatal("fallback identities produced the same device hash")
	}
}

func TestNVMEMaxDataTransferSizeConvertsPagesToBytes(t *testing.T) {
	pages := 32
	output := &SmartctlOutput{
		ModelName:                "nvme-model",
		SerialNumber:             "nvme-serial",
		NVMeMaxDataTransferPages: &pages,
	}
	meta, err := (&NVMEParser{}).ParseMeta(output)
	if err != nil {
		t.Fatal(err)
	}
	if meta.NVMEMaxDataTransferSize == nil {
		t.Fatal("maximum data transfer size was not populated")
	}
	if want := 32 * 4096; *meta.NVMEMaxDataTransferSize != want {
		t.Fatalf("maximum data transfer size = %d, want %d bytes", *meta.NVMEMaxDataTransferSize, want)
	}
}

func TestSCSISSDMetaEstimatesTBW(t *testing.T) {
	usedPct := 10
	writtenGB := 100.0
	output := &SmartctlOutput{
		ModelName:            "scsi-ssd",
		SerialNumber:         "scsi-serial",
		SCSIPctUsedEndurance: &usedPct,
		SCSIErrorCounters: &SCSIErrorCounters{
			Write: &SCSIErrorCountersEntry{
				GigabytesProcessed: &SCSIGigabytes{Value: writtenGB, Units: "GB"},
			},
		},
	}
	meta, err := (&SCSISSDParser{}).ParseMeta(output)
	if err != nil {
		t.Fatal(err)
	}
	if meta.SSDTBWWarranty == nil {
		t.Fatal("SCSI SSD TBW warranty was not estimated")
	}
	want := int64(writtenGB * 1_000_000_000 * 100 / float64(usedPct))
	if *meta.SSDTBWWarranty != want {
		t.Fatalf("TBW = %d, want %d", *meta.SSDTBWWarranty, want)
	}
}
