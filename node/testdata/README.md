# smartctl test fixtures

These JSON files are captured `smartctl -a -j` outputs used by the parser and
threshold tests.

## Provenance

The 18 `smart-*.json` fixtures are copied from the Scrutiny project:

- Upstream: <https://github.com/AnalogJ/scrutiny>
- Path: `webapp/backend/pkg/models/testdata/`
- License: MIT, Copyright (c) 2020 Jason Kulatunga

The remaining fixtures (`linux_*.json`, `mac_*.json`, `scsci_*.json`, and
`scsi_*.json`) were captured by dSentry contributors. Serial numbers, WWNs,
EUI64 namespace IDs, logical unit IDs, and SAS addresses in those files have
been replaced with placeholder values.

See [`NOTICE`](../../NOTICE) for the full MIT license text.
