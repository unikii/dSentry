package smartctl

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

type fixtureExpectation struct {
	file      string
	protocol  string
	metricsOK bool
	threshold int
	model     string
	serial    string
}

var fixtureExpectations = []fixtureExpectation{
	{"scsci_hgst.json", "scsi_hdd", true, 0, "HGST HUH721010AL42C0", "2TJR0000"},
	{"scsi_sg1.json", "scsi_hdd", true, 0, "SEAGATE ST16000NM005J", "ZR600GV10000C00000QZ"},
	{"scsi_sg2.json", "scsi_hdd", true, 0, "SEAGATE ST20000NM002D", "XXXXXXXXxxxxxxxxxxxx"},
	{"scsi_ssd.json", "scsi_ssd", true, 0, "NETAPP X358_TPM4V3T8AME", "1820A0B00000"},
	{"smart-ata2.json", "ata_ssd", true, 0, "X SSD 850 PRO 128GB", "S24ZN902000L"},
	{"smart-ata-date2.json", "ata_hdd", true, 2, "WDC WD140EDFZ-11A0VA0", "9RK1XXXX"},
	{"smart-ata-date.json", "ata_hdd", true, 1, "WDC WD140EDFZ-11A0VA0", "9RK1XXXX"},
	{"smart-ata-failed-scrutiny.json", "ata_ssd", true, 2, "Samsung SSD 840 Series", "S14LNEACC02756X"},
	{"smart-ata-full.json", "ata_ssd", true, 0, "Samsung SSD 860 EVO 500GB", "S3YZNB0KB00864E"},
	{"smart-ata.json", "ata_hdd", true, 1, "WDC WD140EDFZ-11A0VA0", "9RK1XXXX"},
	{"smart-fail2.json", "ata_hdd", true, 2, "Hitachi HDS721050DLE630", "MSK423Y20S3HBC"},
	{"smart-megaraid0.json", "ata_hdd", true, 1, "WD4000FYYX", "XXXXXXXXXXXX"},
	{"smart-megaraid1.json", "ata_hdd", true, 2, "WD4000FYYX", "XXXXXXXXXXXX"},
	{"smart-nvme2.json", "nvme", true, 0, "Force MP510", "yes"},
	{"smart-nvme-failed.json", "nvme", true, 2, "Samsung SSD 970 EVO 500GB", "S466NX0M776250H"},
	{"smart-nvme.json", "nvme", true, 0, "INTEL SSDPEKNW010T8", "BTNH93710FS91P0B"},
	{"smart-pass.json", "ata_hdd", false, 0, "", ""},
	{"smart-raid.json", "scsi_hdd", true, 0, "Intel Raid 1 Volume", "Volume1"},
	{"smart-sat.json", "ata_hdd", true, 1, "", ""},
	{"smart-scsi2.json", "scsi_hdd", true, 0, "SEAGATE ST1200MM0088", "Z4028VRY0000C810BZXB"},
	{"smart-scsi.json", "scsi_hdd", true, 2, "SEAGATE ST4000NM0043", "Z1Z5DWJK0000XXXXXXXX"},
}

func TestFixturePipeline(t *testing.T) {
	for _, fixture := range fixtureExpectations {
		t.Run(fixture.file, func(t *testing.T) {
			data, err := os.ReadFile(filepath.Join("..", "testdata", fixture.file))
			if err != nil {
				t.Fatal(err)
			}

			var output SmartctlOutput
			if err := json.Unmarshal(data, &output); err != nil {
				t.Fatalf("unmarshal: %v", err)
			}
			output.Normalize()

			protocol, err := DetectProtocol(&output)
			if err != nil {
				t.Fatalf("detect protocol: %v", err)
			}
			if protocol != fixture.protocol {
				t.Fatalf("protocol = %q, want %q", protocol, fixture.protocol)
			}

			parser, err := GetParser(protocol)
			if err != nil {
				t.Fatalf("get parser: %v", err)
			}

			meta, err := parser.ParseMeta(&output)
			if err != nil {
				t.Fatalf("parse meta: %v", err)
			}
			if meta.ModelName != fixture.model || meta.SerialNumber != fixture.serial {
				t.Fatalf("meta identity = (%q, %q), want (%q, %q)",
					meta.ModelName, meta.SerialNumber, fixture.model, fixture.serial)
			}

			_, err = parser.ParseMetrics(&output)
			if fixture.metricsOK && err != nil {
				t.Fatalf("parse metrics: %v", err)
			}
			if !fixture.metricsOK && err == nil {
				t.Fatal("expected metrics parse failure")
			}

			_, threshold := ComputeThresholdStatuses(&output, protocol)
			if threshold != fixture.threshold {
				t.Fatalf("threshold status = %d, want %d", threshold, fixture.threshold)
			}
		})
	}
}

func TestOpenFailureFixture(t *testing.T) {
	data, err := os.ReadFile(filepath.Join("..", "testdata", "smart-fail.json"))
	if err != nil {
		t.Fatal(err)
	}
	if _, err := ParseOutput(data); err == nil {
		t.Fatal("expected ParseOutput to fail for device-open error fixture")
	}
}

func TestDetectProtocolRotationRate(t *testing.T) {
	base := &SmartctlOutput{
		Device: DeviceInfo{Type: "ata", Protocol: "ATA"},
		ATASMARTAttributes: &ATASMARTAttributes{Table: []ATASMARTAttribute{
			{ID: 217, Name: "Power_Loss_Protection_Failure", Raw: struct {
				Value  int64  `json:"value"`
				String string `json:"string"`
			}{Value: 0}},
		}},
	}

	t.Run("non-rotation attribute 217 ignored", func(t *testing.T) {
		// Attribute 217 with a vendor name must not influence classification.
		out := *base
		protocol, err := DetectProtocol(&out)
		if err != nil {
			t.Fatal(err)
		}
		if protocol != "ata_hdd" {
			t.Fatalf("protocol = %q, want ata_hdd (default for unknown)", protocol)
		}
	})

	t.Run("named rotation attribute used", func(t *testing.T) {
		out := *base
		out.ATASMARTAttributes.Table[0].Name = "Rotation_Rate"
		out.ATASMARTAttributes.Table[0].Raw.Value = 7200
		protocol, err := DetectProtocol(&out)
		if err != nil {
			t.Fatal(err)
		}
		if protocol != "ata_hdd" {
			t.Fatalf("protocol = %q, want ata_hdd", protocol)
		}
	})

	t.Run("top-level rotation rate preferred", func(t *testing.T) {
		out := *base
		zero := 0
		out.RotationRate = &zero
		protocol, err := DetectProtocol(&out)
		if err != nil {
			t.Fatal(err)
		}
		if protocol != "ata_ssd" {
			t.Fatalf("protocol = %q, want ata_ssd from top-level rotation_rate=0", protocol)
		}
	})
}

func TestHostByteCounterGuards(t *testing.T) {
	mkAttr := func(id int, name string, raw int64) ATASMARTAttribute {
		return ATASMARTAttribute{ID: id, Name: name, Raw: struct {
			Value  int64  `json:"value"`
			String string `json:"string"`
		}{Value: raw}}
	}

	t.Run("non-host attributes are ignored", func(t *testing.T) {
		output := &SmartctlOutput{
			ATASMARTAttributes: &ATASMARTAttributes{Table: []ATASMARTAttribute{
				mkAttr(175, "Power_Loss_Protection_Failure", 10),
				mkAttr(174, "Unexpected_Power_Loss", 10),
			}},
		}
		metrics := &DeviceMetrics{}
		parseUniversalATAMetrics(metrics, buildAttributeMap(output.ATASMARTAttributes.Table), output)
		if metrics.TotalBytesWritten != nil || metrics.TotalBytesRead != nil {
			t.Fatalf("vendor attributes misread as byte counters: written=%v read=%v",
				metrics.TotalBytesWritten, metrics.TotalBytesRead)
		}
	})

	t.Run("host-named attributes are used", func(t *testing.T) {
		output := &SmartctlOutput{
			ATASMARTAttributes: &ATASMARTAttributes{Table: []ATASMARTAttribute{
				mkAttr(175, "Host_Writes_MiB", 10),
				mkAttr(174, "Host_Reads_MiB", 10),
			}},
		}
		metrics := &DeviceMetrics{}
		parseUniversalATAMetrics(metrics, buildAttributeMap(output.ATASMARTAttributes.Table), output)
		want := int64(10 * 1024 * 1024)
		if metrics.TotalBytesWritten == nil || *metrics.TotalBytesWritten != want {
			t.Fatalf("TotalBytesWritten = %v, want %d", metrics.TotalBytesWritten, want)
		}
		if metrics.TotalBytesRead == nil || *metrics.TotalBytesRead != want {
			t.Fatalf("TotalBytesRead = %v, want %d", metrics.TotalBytesRead, want)
		}
	})
}
