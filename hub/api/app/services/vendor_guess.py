#!/usr/bin/env python3
"""
Vendor matching for storage devices.

Matches a vendor name from device metadata using:
1. Model name prefix/substring matching (ATA/SCSI/NVMe model strings)
2. NVMe PCI vendor ID lookup
3. Existing vendor field from smartctl (fallback)

Usage:
    from app.services.vendor_guess import guess_vendor

    vendor = guess_vendor(device_meta_dict)
"""

import json
import os
from typing import Any

_DEFAULT_PATH = os.path.join(os.path.dirname(__file__), "vendors.json")

_MODEL_PREFIXES: dict[str, str] = {}
_NVME_PCI_VENDORS: dict[str, str] = {}
_loaded = False


def _ensure_loaded() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    try:
        with open(_DEFAULT_PATH) as f:
            data = json.load(f)
        _MODEL_PREFIXES.update(data.get("model_prefixes", {}))
        _NVME_PCI_VENDORS.update(data.get("nvme_pci_vendors", {}))
    except FileNotFoundError:
        pass


def _normalize(s: str | None) -> str:
    return (s or "").strip().lower()


def match_by_model(model_name: str | None) -> str | None:
    m = _normalize(model_name)
    if not m:
        return None

    best_prefix: tuple[int, str] | None = None
    best_substr: tuple[int, str] | None = None

    for prefix, vendor in _MODEL_PREFIXES.items():
        if m.startswith(prefix):
            if best_prefix is None or len(prefix) > best_prefix[0]:
                best_prefix = (len(prefix), vendor)
        elif prefix in m:
            if best_substr is None or len(prefix) > best_substr[0]:
                best_substr = (len(prefix), vendor)

    if best_prefix:
        return best_prefix[1]
    if best_substr:
        return best_substr[1]
    return None


def match_by_nvme_pci(pci_vendor_id: str | None) -> str | None:
    vid = (pci_vendor_id or "").strip()
    return _NVME_PCI_VENDORS.get(vid)


def _extract_nvme_pci_vid(meta: dict) -> str | None:
    ext = meta.get("device_ext")
    if isinstance(ext, str):
        # Database rows carry device_ext as a JSON string, not a dict.
        try:
            ext = json.loads(ext)
        except (json.JSONDecodeError, TypeError):
            ext = None
    if isinstance(ext, dict):
        vid = ext.get("pci_vendor_id")
        if vid:
            return vid
    if "nvme_pci_vendor_id" in meta:
        vid_raw = meta.get("nvme_pci_vendor_id")
        if vid_raw is not None:
            return str(vid_raw)
        return None
    if "pci_vendor_id" in meta:
        vid = meta.get("pci_vendor_id")
        if vid is not None:
            return str(vid)
    return None


def guess_vendor(meta: dict[str, Any]) -> str | None:
    _ensure_loaded()

    model_name = meta.get("model_name", "")

    vendor = match_by_model(model_name)
    if vendor:
        return vendor

    device_type = _normalize(meta.get("device_type") or meta.get("protocol", ""))
    if device_type == "nvme":
        pci_vid = _extract_nvme_pci_vid(meta)
        vendor = match_by_nvme_pci(pci_vid)
        if vendor:
            return vendor

    return meta.get("vendor") or None


__all__ = ["guess_vendor"]
