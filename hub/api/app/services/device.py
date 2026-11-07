import asyncio
import base64
import json
import logging
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from aiosqlite import Connection

from app.metrics import _build_line_protocol
from app.utils import paginate_offset, sort_direction, stringify_timestamps

logger = logging.getLogger("dsentry.device")


# The decompressed view is capped to avoid decompression bombs.
MAX_DECOMPRESSED_SIZE = 5 * 1024 * 1024

_SCHEMA: dict | None = None

_SAFE_VALUE_RE = re.compile(r'^[a-zA-Z0-9_\-:\.\+\s]+$')


def _escape_like(s: str) -> str:
    """Escape LIKE wildcards so keyword tags match literally."""
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _load_metrics_schema() -> dict:
    global _SCHEMA
    if _SCHEMA is not None:
        return _SCHEMA
    here = Path(__file__).resolve()
    candidates: list[Path] = [
        Path("schemas/metrics_schema.json"),
        Path.cwd() / "schemas" / "metrics_schema.json",
        Path("/hub/schemas/metrics_schema.json"),
    ]
    candidates.extend(p / "schemas" / "metrics_schema.json" for p in here.parents)
    for p in candidates:
        try:
            if p.exists():
                with open(p) as f:
                    _SCHEMA = json.load(f)
                return _SCHEMA
        except OSError:
            continue
    raise FileNotFoundError(
        "metrics_schema.json not found. Searched paths: " + ", ".join(str(p) for p in candidates)
    )


def get_metric_fields() -> list[dict]:
    schema = _load_metrics_schema()
    return schema["measurements"]["device_metric"]["fields"]


def _metric_meta(name: str) -> dict | None:
    for f in get_metric_fields():
        if f["name"] == name:
            return f
    return None


THRESHOLD_META_FIELD = "smart_threshold_status"

DEVICE_EXT_MAP = {
    "wwn": "wwn",
    "ssd_tbw_warranty": "ssd_tbw_warranty",
    "nvme_pci_vendor_id": "pci_vendor_id",
    "nvme_pci_vendor_subsystem_id": "pci_vendor_subsystem_id",
    "nvme_ieee_oui_identifier": "ieee_oui_identifier",
    "nvme_available_spare_threshold": "available_spare_threshold",
    "nvme_warn_comp_temp_threshold": "warn_comp_temp_threshold",
    "nvme_critical_comp_temp_threshold": "critical_comp_temp_threshold",
    "nvme_maximum_data_transfer_size": "maximum_data_transfer_size",
    "hdd_form_factor": "form_factor",
    "hdd_rotation_rate": "rotation_rate",
    "ata_min_temperature_celsius": "min_temperature_celsius",
    "ata_max_temperature_celsius": "max_temperature_celsius",
    "scsi_manufacturing_date": "manufacturing_date",
    "scsi_drive_trip_temperature": "drive_trip_temperature",
    "scsi_hdd_specified_cycle_count": "hdd_specified_cycle_count",
    "scsi_hdd_specified_load_unload_count": "hdd_specified_load_unload_count",
}


def _map_device_type(raw: str | None) -> str:
    if not isinstance(raw, str):
        return "nvme"
    raw = raw.lower()
    if raw in {"nvme", "ata_hdd", "ata_ssd", "scsi_hdd", "scsi_ssd"}:
        return raw
    if raw in {"scsi", "sas"}:
        return "scsi_hdd"
    return "nvme"


def _coerce_str(val: Any) -> str | None:
    if isinstance(val, str) and len(val) <= 100:
        return val
    return None


def _coerce_int(val: Any) -> int | None:
    if isinstance(val, bool):
        return int(val)
    if isinstance(val, int):
        return val
    if isinstance(val, float) and val.is_integer():
        return int(val)
    return None


def meta_to_common(meta: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(meta, dict):
        meta = {}
    result: dict[str, Any] = {
        "serial_number": _coerce_str(meta.get("serial_number")) or "",
        "model_name": _coerce_str(meta.get("model_name")) or "",
        "vendor": _coerce_str(meta.get("vendor")),
        "total_capacity_bytes": _coerce_int(meta.get("total_capacity_bytes")) or 0,
        "firmware_version": _coerce_str(meta.get("firmware_version")),
        "smart_status": _coerce_int(meta.get("smart_status")),
        "smart_enabled": _coerce_int(meta.get("smart_enabled")),
        "smart_available": _coerce_int(meta.get("smart_available")),
        "device_name": _coerce_str(meta.get("device_name")),
    }
    result["device_type"] = _map_device_type(
        _coerce_str(meta.get("device_type")) or _coerce_str(meta.get("protocol"))
    )
    result["using_protocol"] = (
        _coerce_str(meta.get("using_protocol")) or _coerce_str(meta.get("protocol"))
    )
    result["threshold_status"] = _coerce_int(meta.get(THRESHOLD_META_FIELD)) or 0
    return result


def meta_to_device_ext(meta: dict[str, Any] | None) -> dict[str, Any] | None:
    if meta is None:
        return None
    ext: dict[str, Any] = {}
    for go_field, ext_key in DEVICE_EXT_MAP.items():
        val = meta.get(go_field)
        if val is not None:
            ext[ext_key] = val
    return ext if ext else None


async def register_devices(
    db: Connection,
    user_id: int,
    devices: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Register/update devices inside the caller's transaction.

    Devices belong to the user, not to the node that first reported them:
    moving a disk to another machine reuses the same row and keeps its
    history. Returns per-device results plus line-protocol samples for the
    initial metrics; the caller sends them to VictoriaMetrics after committing.
    """
    device_hashes = list(
        dict.fromkeys(d.get("device_hash", "") for d in devices if d.get("device_hash"))
    )
    existing_map: dict[str, dict[str, Any]] = {}
    if device_hashes:
        placeholders = ", ".join("?" for _ in device_hashes)
        cursor = await db.execute(
            f'''SELECT id, device_hash, meta_hash, archived FROM device
            WHERE device_hash IN ({placeholders}) AND user_id = ?''',
            (*device_hashes, user_id),
        )
        rows = await cursor.fetchall()
        existing_map = {r["device_hash"]: dict(r) for r in rows}

    results = []
    metric_lines: list[str] = []
    seen_hashes: set[str] = set()

    for dev in devices:
        device_hash = dev.get("device_hash", "")
        meta_hash = dev.get("meta_hash", "")
        if not device_hash or device_hash in seen_hashes:
            continue
        seen_hashes.add(device_hash)

        meta = dev.get("device_meta")
        if not isinstance(meta, dict):
            meta = {}
        initial_metrics = dev.get("initial_metrics")

        existing = existing_map.get(device_hash)

        if existing and not existing["archived"]:
            device_id = existing["id"]
            if existing["meta_hash"] != meta_hash:
                if meta:
                    await _update_device_meta(db, device_id, meta, meta_hash)
                else:
                    await db.execute(
                        "UPDATE device SET meta_hash = ? WHERE id = ?",
                        (meta_hash, device_id),
                    )
            results.append({
                "device_hash": device_hash,
                "device_id": device_id,
            })
        elif existing and existing["archived"]:
            # Keep the user's archive decision: a node re-registering its
            # devices after a state loss must not silently unhide them.
            # Metadata is still refreshed so unarchiving later shows current
            # data.
            device_id = existing["id"]
            if existing["meta_hash"] != meta_hash:
                if meta:
                    await _update_device_meta(db, device_id, meta, meta_hash)
                else:
                    await db.execute(
                        "UPDATE device SET meta_hash = ? WHERE id = ?",
                        (meta_hash, device_id),
                    )
            results.append({
                "device_hash": device_hash,
                "device_id": device_id,
            })
        else:
            device_id = await _insert_device(
                db, user_id, device_hash, meta_hash, meta
            )
            results.append({
                "device_hash": device_hash,
                "device_id": device_id,
            })

        if initial_metrics and isinstance(initial_metrics, dict):
            line = _metrics_to_line_protocol(device_id, user_id, initial_metrics)
            if line:
                metric_lines.append(line)

    return results, metric_lines


async def _insert_device(
    db: Connection,
    user_id: int,
    device_hash: str,
    meta_hash: str,
    meta: dict[str, Any],
) -> int:
    common = meta_to_common(meta)
    ext = meta_to_device_ext(meta)
    ext_json = json.dumps(ext) if ext else None

    cursor = await db.execute(
        "INSERT INTO device (user_id, device_type, using_protocol, device_ext, "
        "device_hash, meta_hash, device_name, serial_number, model_name, vendor, "
        "total_capacity_bytes, firmware_version, smart_status, smart_enabled, smart_available, "
        "threshold_status) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id",
        (
            user_id,
            common.get("device_type"),
            common.get("using_protocol"),
            ext_json,
            device_hash, meta_hash,
            common.get("device_name", ""),
            common.get("serial_number"),
            common.get("model_name"),
            common.get("vendor"),
            common.get("total_capacity_bytes"),
            common.get("firmware_version"),
            common.get("smart_status"),
            common.get("smart_enabled"),
            common.get("smart_available"),
            common.get("threshold_status", 0),
        ),
    )
    row = await cursor.fetchone()
    return row["id"]


async def _update_device_meta(
    db: Connection,
    device_id: int,
    meta: dict[str, Any],
    meta_hash: str,
) -> None:
    common = meta_to_common(meta)
    ext = meta_to_device_ext(meta)
    ext_json = json.dumps(ext) if ext else None

    await db.execute(
        "UPDATE device SET meta_hash = ?, "
        "device_type = ?, using_protocol = ?, device_ext = ?, "
        "device_name = ?, "
        "serial_number = ?, model_name = ?, vendor = ?, "
        "total_capacity_bytes = ?, firmware_version = ?, "
        "smart_status = ?, smart_enabled = ?, smart_available = ?, "
        "threshold_status = ? "
        "WHERE id = ?",
        (
            meta_hash,
            common.get("device_type"),
            common.get("using_protocol"),
            ext_json,
            common.get("device_name", ""),
            common.get("serial_number"),
            common.get("model_name"),
            common.get("vendor"),
            common.get("total_capacity_bytes"),
            common.get("firmware_version"),
            common.get("smart_status"),
            common.get("smart_enabled"),
            common.get("smart_available"),
            common.get("threshold_status", 0),
            device_id,
        ),
    )


async def list_devices(
    db: Connection,
    user_id: int,
    plimit: int = 50,
    pnum: int = 1,
    node_id: int | None = None,
    device_type: str | None = None,
    archived: bool | None = None,
    keyword: str | None = None,
    sort_by: str = "reg_at",
    sort_order: str = "desc",
) -> tuple[list[dict], int]:
    offset = paginate_offset(pnum, plimit)
    conditions = ["d.user_id = ?"]
    params: list[Any] = [user_id]

    if archived is None:
        conditions.append("d.archived = 0")
    else:
        conditions.append("d.archived = ?")
        params.append(1 if archived else 0)

    if node_id is not None:
        # Devices are user-scoped, but the nodes page still needs a "devices
        # last pushed by this node" view. That association is soft: it comes
        # from node.last_device_push, never from a hard device->node link.
        cursor = await db.execute(
            "SELECT last_device_push FROM node WHERE id = ? AND user_id = ?",
            (node_id, user_id),
        )
        node_row = await cursor.fetchone()
        device_ids: list[int] = []
        if node_row and node_row[0]:
            try:
                parsed_ids = json.loads(node_row[0])
                if isinstance(parsed_ids, list):
                    device_ids = [int(i) for i in parsed_ids if isinstance(i, int)]
            except (json.JSONDecodeError, TypeError, ValueError):
                device_ids = []

        if device_ids:
            conds = ["d.id = ?" for _ in device_ids]
            conditions.append(f"({' OR '.join(conds)})")
            params.extend(device_ids)
        else:
            # An unknown node or a node that has not pushed devices yet must
            # return no devices, not every device owned by the user.
            conditions.append("1 = 0")

    if device_type:
        conditions.append("d.device_type = ?")
        params.append(device_type)

    if keyword:
        # Keyword covers model name and tags. Tags are a JSON array of strings:
        # match each element via json_each (all tags are stored as UTF-8 JSON,
        # see update_device_tags).
        # Split on whitespace/commas (incl. full-width，and、) so multi-tag
        # searches like "prod db" or "prod,db" match devices having every
        # token in either column.
        tokens = [t for t in re.split(r"[\s,，、]+", keyword.strip()) if t]
        for tok in tokens:
            kw = f"%{_escape_like(tok)}%"
            conditions.append(
                "(d.model_name LIKE ? ESCAPE '\\' OR EXISTS ("
                "SELECT 1 FROM json_each(CASE WHEN json_valid(d.tags) THEN d.tags ELSE '[]' END) "
                "WHERE value LIKE ? ESCAPE '\\'))"
            )
            params.extend([kw, kw])

    where = " AND ".join(conditions)

    sort_column = _ALLOWED_SORT_COLUMNS.get(sort_by, "d.reg_at")
    direction = sort_direction(sort_order)

    cursor = await db.execute(f"SELECT COUNT(*) FROM device d WHERE {where}", params)
    row = await cursor.fetchone()
    total = row[0] if row else 0

    query = f'''
        SELECT d.* FROM device d
        WHERE {where}
        ORDER BY {sort_column} {direction}
        LIMIT ? OFFSET ?
    '''
    params.extend([plimit, offset])

    cursor = await db.execute(query, params)
    rows = await cursor.fetchall()
    return [dict(r) for r in rows], total


async def get_device(db: Connection, device_id: int, user_id: int) -> dict | None:
    cursor = await db.execute(
        "SELECT * FROM device WHERE id = ? AND user_id = ?",
        (device_id, user_id),
    )
    row = await cursor.fetchone()
    return dict(row) if row else None


async def device_owned(db: Connection, device_id: int, user_id: int) -> bool:
    cursor = await db.execute(
        "SELECT id FROM device WHERE id = ? AND user_id = ? AND archived = 0",
        (device_id, user_id),
    )
    return await cursor.fetchone() is not None


async def update_device_tags(
    db: Connection,
    device_id: int,
    user_id: int,
    tags: list[str],
) -> dict | None:
    # UTF-8 JSON: raw non-ASCII chars, never backslash-u escapes.
    tags_json = json.dumps(tags, ensure_ascii=False)
    # Archived devices remain editable by their owner; the UI shows the tag
    # editor for them and tags are useful when deciding whether to unarchive.
    cursor = await db.execute(
        "UPDATE device SET tags = ? WHERE id = ? AND user_id = ? RETURNING *",
        (tags_json, device_id, user_id),
    )
    row = await cursor.fetchone()
    await db.commit()
    return dict(row) if row else None


async def clear_device_last_event(db: Connection, device_id: int, user_id: int) -> None:
    await db.execute(
        "UPDATE device SET last_event_at = NULL WHERE id = ? AND user_id = ?",
        (device_id, user_id),
    )


async def delete_device(db: Connection, device_id: int, user_id: int) -> bool:
    cursor = await db.execute(
        "UPDATE device SET archived = 1 WHERE id = ? AND user_id = ? RETURNING id",
        (device_id, user_id),
    )
    row = await cursor.fetchone()
    await db.commit()
    return row is not None


# ---------------------------------------------------------------------------
# VictoriaMetrics-backed metrics
# ---------------------------------------------------------------------------


def _metrics_to_line_protocol(
    device_id: int,
    user_id: int,
    metrics: dict[str, Any],
    ts_s: int | None = None,
) -> str:
    fields: dict[str, object] = {}
    for f in get_metric_fields():
        val = metrics.get(f["go_field"])
        # Every schema field is numeric; silently drop anything else so a
        # malformed (or malicious) node value cannot poison the batch write.
        if isinstance(val, bool) or isinstance(val, (int, float)):
            fields[f["name"]] = val

    return _build_line_protocol(
        measurement="device_metric",
        tags={"device_id": str(device_id)},
        fields=fields,
        ts_s=ts_s,
    )


async def push_metas(
    db: Connection,
    user_id: int,
    metas: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    hashes = [m.get("device_hash", "") for m in metas if m.get("device_hash")]
    if not hashes:
        return [{"device_hash": m.get("device_hash", ""), "updated": False} for m in metas]

    placeholders = ", ".join("?" for _ in hashes)
    cursor = await db.execute(
        f'''SELECT id, device_hash, meta_hash FROM device
        WHERE device_hash IN ({placeholders}) AND user_id = ? AND archived = 0''',
        (*hashes, user_id),
    )
    rows = await cursor.fetchall()
    hash_to_device = {r["device_hash"]: {"id": r["id"], "meta_hash": r["meta_hash"]} for r in rows}

    results = []
    for m in metas:
        device_hash = m.get("device_hash", "")
        meta_hash = m.get("meta_hash", "")
        meta = m.get("device_meta")

        if not device_hash:
            results.append({"device_hash": "", "updated": False})
            continue

        dev = hash_to_device.get(device_hash)
        if dev is None:
            results.append({"device_hash": device_hash, "updated": False})
            continue

        if dev["meta_hash"] == meta_hash:
            results.append({"device_hash": device_hash, "updated": False})
            continue

        if meta is not None:
            await _update_device_meta(db, dev["id"], meta, meta_hash)
        else:
            await db.execute(
                "UPDATE device SET meta_hash = ? WHERE id = ?",
                (meta_hash, dev["id"]),
            )

        results.append({"device_hash": device_hash, "updated": True})

    return results


async def any_device_hash_known(
    db: Connection, user_id: int, hashes: list[str]
) -> bool:
    """Whether any of the hashes belongs to this user (archived included)."""
    if not hashes:
        return False
    placeholders = ", ".join("?" for _ in hashes)
    cursor = await db.execute(
        f"SELECT 1 FROM device WHERE device_hash IN ({placeholders}) "
        f"AND user_id = ? LIMIT 1",
        (*hashes, user_id),
    )
    return await cursor.fetchone() is not None


async def push_raws(
    db: Connection,
    user_id: int,
    raws: dict[int, bytes],
    timestamps: dict[int, str] | None = None,
) -> None:
    device_ids = list(raws.keys())
    if not device_ids:
        return

    placeholders = ", ".join("?" for _ in device_ids)
    cursor = await db.execute(
        f"SELECT id FROM device WHERE id IN ({placeholders}) AND user_id = ? "
        f"AND archived = 0",
        (*device_ids, user_id),
    )
    rows = await cursor.fetchall()
    valid_ids = {r["id"] for r in rows}

    for device_id, raw_data in raws.items():
        if device_id not in valid_ids:
            continue
        collected_at = (timestamps or {}).get(device_id)
        if collected_at:
            await db.execute(
                "INSERT INTO device_raw (device_id, raw_output, add_at) VALUES (?, ?, ?)",
                (device_id, raw_data, collected_at),
            )
        else:
            await db.execute(
                "INSERT INTO device_raw (device_id, raw_output) VALUES (?, ?)",
                (device_id, raw_data),
            )


def _format_raw_list_row(row: dict) -> dict:
    return stringify_timestamps(dict(row), "add_at")


_ALLOWED_SORT_COLUMNS = {
    "reg_at": "d.reg_at",
    "capacity": "d.total_capacity_bytes",
}


# Runs in a separate interpreter so a decompression bomb can only exhaust the
# child's address space. The child checks the output after every input chunk
# and exits non-zero as soon as the limit is crossed. On POSIX, RLIMIT_AS is
# lowered before brotli is imported; the web process itself never allocates
# attacker-controlled output.
_DECOMPRESS_SCRIPT = r"""
import sys

limit = int(sys.argv[1])
try:
    import resource
    cap = limit + 64 * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (cap, cap))
except Exception:
    pass

import brotli

data = sys.stdin.buffer.read()
out = bytearray()
decoder = brotli.Decompressor()
for offset in range(0, len(data), 4096):
    out.extend(decoder.process(data[offset:offset + 4096]))
    if len(out) > limit:
        sys.exit(3)
if not decoder.is_finished():
    sys.exit(3)
sys.stdout.buffer.write(out)
"""


def _decompress_bounded(raw: bytes, limit: int) -> bytes | None:
    """Decompress brotli data without exceeding the caller's size budget."""
    if not raw:
        return b""

    try:
        proc = subprocess.run(
            [sys.executable, "-c", _DECOMPRESS_SCRIPT, str(limit)],
            input=raw,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    if proc.returncode != 0 or len(proc.stdout) > limit:
        return None
    return proc.stdout


def _format_raw_row(row: dict) -> dict:
    d = dict(row)
    raw = d.get("raw_output")
    if raw is not None:
        try:
            decompressed = _decompress_bounded(raw, MAX_DECOMPRESSED_SIZE)
            if decompressed is None:
                d["raw_output"] = "[Raw output exceeds size limit]"
            else:
                d["raw_output"] = decompressed.decode("utf-8")
        except Exception:
            d["raw_output"] = base64.b64encode(raw).decode()
    if d.get("add_at"):
        d["add_at"] = str(d["add_at"])
    return d


async def get_device_raws(
    db: Connection,
    device_id: int,
    user_id: int,
    start: str | None = None,
    end: str | None = None,
) -> list[dict] | None:
    device = await get_device(db, device_id, user_id)
    if device is None:
        return None

    conditions = ["device_id = ?"]
    params: list[Any] = [device_id]
    if start:
        # The UI sends date-only values; include the whole end day rather than
        # silently dropping everything after midnight. datetime() parses both
        # storage formats (SQLite defaults use a space, node-supplied values
        # arrive as ISO-8601 with a T and offset) instead of comparing the raw
        # strings lexicographically.
        conditions.append("datetime(add_at) >= datetime(?)")
        params.append(f"{start} 00:00:00" if len(start) == 10 else start)
    if end:
        conditions.append("datetime(add_at) <= datetime(?)")
        params.append(f"{end} 23:59:59" if len(end) == 10 else end)

    cursor = await db.execute(
        "SELECT id, device_id, add_at "
        f"FROM device_raw WHERE {' AND '.join(conditions)} "
        "ORDER BY datetime(add_at) DESC, id DESC LIMIT 50",
        params,
    )

    rows = await cursor.fetchall()
    return [_format_raw_list_row(dict(r)) for r in rows]


async def get_device_raw(
    db: Connection,
    raw_id: int,
    device_id: int,
    user_id: int,
) -> dict | None:
    device = await get_device(db, device_id, user_id)
    if device is None:
        return None

    cursor = await db.execute(
        "SELECT id, device_id, raw_output, add_at "
        "FROM device_raw WHERE id = ? AND device_id = ?",
        (raw_id, device_id),
    )
    row = await cursor.fetchone()
    if row is None:
        return None

    return await asyncio.to_thread(_format_raw_row, dict(row))


async def get_device_events(
    db: Connection,
    device_id: int,
    user_id: int,
) -> list[dict] | None:
    device = await get_device(db, device_id, user_id)
    if device is None:
        return None

    cursor = await db.execute(
        "SELECT e.*, d.model_name AS device_name "
        "FROM events e "
        "LEFT JOIN device d ON e.device_id = d.id "
        "WHERE e.device_id = ? AND e.user_id = ? "
        "ORDER BY datetime(e.add_at) DESC, e.id DESC",
        (device_id, user_id),
    )

    rows = await cursor.fetchall()
    return [dict(r) for r in rows]
