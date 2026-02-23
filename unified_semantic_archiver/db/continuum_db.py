"""
Unified Semantic Archiver - continuum database micro ORM.
Lightweight CRUD over SQLite; no heavy migrations.
"""

from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path
from typing import Any

_SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"

# Geohash base32 alphabet (standard)
_GEOHASH_ALPHABET = "0123456789bcdefghjkmnopqrstuvwxyz"

# Earth radius in miles for Haversine
_EARTH_RADIUS_MI = 3958.8


def _geohash_encode(lat: float, lon: float, precision: int = 7) -> str:
    """Encode lat/lon to base32 geohash (precision = character count)."""
    lat_lo, lat_hi = -90.0, 90.0
    lon_lo, lon_hi = -180.0, 180.0
    bits = 0
    bit = 0
    result = []
    while len(result) < precision:
        if bit % 2 == 0:
            mid = (lon_lo + lon_hi) / 2
            if lon >= mid:
                lon_lo = mid
                bits = (bits << 1) + 1
            else:
                lon_hi = mid
                bits <<= 1
        else:
            mid = (lat_lo + lat_hi) / 2
            if lat >= mid:
                lat_lo = mid
                bits = (bits << 1) + 1
            else:
                lat_hi = mid
                bits <<= 1
        bit += 1
        if bit == 5:
            result.append(_GEOHASH_ALPHABET[bits])
            bits = 0
            bit = 0
    return "".join(result)


def _haversine_mi(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance in miles between two WGS84 points."""
    a = math.radians(lat2 - lat1)
    b = math.radians(lon2 - lon1)
    x = math.sin(a / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(b / 2) ** 2
    return 2 * _EARTH_RADIUS_MI * math.asin(math.sqrt(min(1.0, x)))


def get_connection(db_path: str | Path) -> sqlite3.Connection:
    """Open connection to continuum DB; ensures schema exists."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """Run schema.sql to create tables if not exist."""
    with open(_SCHEMA_PATH, encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.commit()


class ContinuumDb:
    """Micro ORM for continuum SQLite database."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = get_connection(self.db_path)
        init_schema(conn)
        conn.close()

    def _conn(self) -> sqlite3.Connection:
        return get_connection(self.db_path)

    # --- continuum_meta ---
    def meta_get(self, key: str) -> str | None:
        with self._conn() as c:
            row = c.execute("SELECT value FROM continuum_meta WHERE key = ?", (key,)).fetchone()
            return row["value"] if row else None

    def meta_set(self, key: str, value: str) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO continuum_meta (key, value, updated_at) VALUES (?, ?, datetime('now'))",
                (key, value),
            )
            c.commit()

    # --- spatial_4d ---
    def spatial_4d_insert(self, bounds4_json: str, payload_type: str | None = None, payload_id: int | None = None) -> int:
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO spatial_4d (bounds4_json, payload_type, payload_id) VALUES (?, ?, ?)",
                (bounds4_json, payload_type, payload_id),
            )
            c.commit()
            return cur.lastrowid

    def spatial_4d_list(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM spatial_4d ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]

    # --- document_blobs ---
    def document_blob_insert(self, tar_hash: str, path: str, mime_type: str | None = None) -> int:
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO document_blobs (tar_hash, path, mime_type) VALUES (?, ?, ?)",
                (tar_hash, path, mime_type),
            )
            c.commit()
            return cur.lastrowid

    def document_blob_list(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM document_blobs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]

    # --- semantic_chunks ---
    def semantic_chunk_insert(
        self,
        media_type: str,
        chunk_key: str,
        description_text: str | None = None,
        diff_blob_ref: str | None = None,
        parent_id: int | None = None,
        quad_path: str | None = None,
    ) -> int:
        with self._conn() as c:
            cur = c.execute(
                """INSERT INTO semantic_chunks (media_type, chunk_key, description_text, diff_blob_ref, parent_id, quad_path)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (media_type, chunk_key, description_text, diff_blob_ref, parent_id, quad_path),
            )
            c.commit()
            return cur.lastrowid

    def semantic_chunk_list(self, media_type: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        with self._conn() as c:
            if media_type:
                rows = c.execute(
                    "SELECT * FROM semantic_chunks WHERE media_type = ? ORDER BY id DESC LIMIT ?",
                    (media_type, limit),
                ).fetchall()
            else:
                rows = c.execute("SELECT * FROM semantic_chunks ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]

    # --- unique_kernels ---
    def unique_kernel_insert(
        self,
        chunk_id: int,
        source_compressor: str,
        residual_metric: float | None = None,
        attempt_count: int = 0,
        status: str = "pending",
    ) -> int:
        with self._conn() as c:
            cur = c.execute(
                """INSERT INTO unique_kernels (chunk_id, source_compressor, residual_metric, attempt_count, status)
                   VALUES (?, ?, ?, ?, ?)""",
                (chunk_id, source_compressor, residual_metric, attempt_count, status),
            )
            c.commit()
            return cur.lastrowid

    def unique_kernel_list(self, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        with self._conn() as c:
            if status:
                rows = c.execute(
                    "SELECT * FROM unique_kernels WHERE status = ? ORDER BY id DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            else:
                rows = c.execute("SELECT * FROM unique_kernels ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]

    def unique_kernel_update_status(self, kernel_id: int, status: str, residual_metric: float | None = None) -> None:
        with self._conn() as c:
            if residual_metric is not None:
                c.execute(
                    "UPDATE unique_kernels SET status = ?, residual_metric = ?, attempt_count = attempt_count + 1 WHERE id = ?",
                    (status, residual_metric, kernel_id),
                )
            else:
                c.execute(
                    "UPDATE unique_kernels SET status = ?, attempt_count = attempt_count + 1 WHERE id = ?",
                    (status, kernel_id),
                )
            c.commit()

    # --- compression_runs ---
    def compression_run_insert(
        self,
        strategy: str,
        media_id: int | None = None,
        config_json: str | None = None,
        output_hash: str | None = None,
    ) -> int:
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO compression_runs (media_id, strategy, config_json, output_hash) VALUES (?, ?, ?, ?)",
                (media_id, strategy, config_json, output_hash),
            )
            c.commit()
            return cur.lastrowid

    def compression_run_list(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM compression_runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]

    # --- research_suggestions ---
    def research_suggestion_insert(
        self,
        source: str,
        recommendation_text: str,
        context_json: str | None = None,
        status: str = "pending",
    ) -> int:
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO research_suggestions (source, context_json, recommendation_text, status) VALUES (?, ?, ?, ?)",
                (source, context_json, recommendation_text, status),
            )
            c.commit()
            return cur.lastrowid

    def research_suggestion_list(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM research_suggestions ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]

    # --- library_documents ---
    def library_document_insert(
        self,
        document_type: str,
        blob_ref: str | None = None,
        url: str | None = None,
        type_metadata: str | dict | None = None,
        owner_id: str | None = None,
        tenant_id: str = "default",
        lat: float | None = None,
        lon: float | None = None,
        altitude_m: float | None = None,
    ) -> int:
        geohash = None
        if lat is not None and lon is not None:
            geohash = _geohash_encode(lat, lon, 7)
        tenant = (tenant_id or "").strip() or "default"
        meta_str = json.dumps(type_metadata) if isinstance(type_metadata, dict) else type_metadata
        with self._conn() as c:
            cur = c.execute(
                """INSERT INTO library_documents
                   (document_type, blob_ref, url, type_metadata, owner_id, tenant_id, lat, lon, altitude_m, geohash, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
                (document_type, blob_ref, url, meta_str, owner_id, tenant, lat, lon, altitude_m, geohash),
            )
            c.commit()
            return cur.lastrowid

    def library_document_get(self, doc_id: int, tenant_id: str = "default") -> dict[str, Any] | None:
        tenant = (tenant_id or "").strip() or "default"
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM library_documents WHERE id = ? AND tenant_id = ?",
                (doc_id, tenant),
            ).fetchone()
            return dict(row) if row else None

    def library_document_list(
        self,
        document_type: str | None = None,
        tenant_id: str = "default",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        tenant = (tenant_id or "").strip() or "default"
        with self._conn() as c:
            if document_type:
                rows = c.execute(
                    "SELECT * FROM library_documents WHERE tenant_id = ? AND document_type = ? ORDER BY id DESC LIMIT ?",
                    (tenant, document_type, limit),
                ).fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM library_documents WHERE tenant_id = ? ORDER BY id DESC LIMIT ?",
                    (tenant, limit),
                ).fetchall()
            return [dict(r) for r in rows]

    def library_document_search(
        self,
        document_type: str | None = None,
        q: str | None = None,
        lat: float | None = None,
        lon: float | None = None,
        distance_mi: float | str | None = None,
        tenant_id: str = "default",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        tenant = (tenant_id or "").strip() or "default"
        with self._conn() as c:
            sql = "SELECT * FROM library_documents WHERE tenant_id = ?"
            params: list[Any] = [tenant]
            if document_type:
                sql += " AND document_type = ?"
                params.append(document_type)
            if q:
                sql += " AND (type_metadata LIKE ? OR url LIKE ?)"
                params.extend([f"%{q}%", f"%{q}%"])
            sql += " ORDER BY id DESC"
            rows = c.execute(sql, params).fetchall()
            rows = [dict(r) for r in rows]

        # Location filter in Python (Haversine / same bucket)
        if lat is not None and lon is not None and distance_mi is not None and distance_mi != "infinite":
            try:
                dist = float(distance_mi)
            except (TypeError, ValueError):
                dist = None
            if dist is not None:
                if dist == 0:
                    bucket = _geohash_encode(lat, lon, 7)
                    rows = [r for r in rows if r.get("geohash") == bucket]
                else:
                    rows = [
                        r for r in rows
                        if r.get("lat") is not None and r.get("lon") is not None
                        and _haversine_mi(lat, lon, float(r["lat"]), float(r["lon"])) <= dist
                    ]

        return rows[:limit]

    # --- astral_body_catalog ---
    def astral_body_insert(
        self,
        body_id: str,
        name: str,
        kind: str,
        mass_kg: float | None = None,
        radius_m: float | None = None,
        parent_body_id: str | None = None,
        frame_id: str | None = None,
        tenant_id: str = "default",
    ) -> int:
        tenant = (tenant_id or "").strip() or "default"
        with self._conn() as c:
            cur = c.execute(
                """INSERT INTO astral_body_catalog
                   (body_id, name, kind, mass_kg, radius_m, parent_body_id, frame_id, tenant_id, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
                (body_id, name, kind, mass_kg, radius_m, parent_body_id, frame_id, tenant),
            )
            c.commit()
            return cur.lastrowid

    def astral_body_get(self, body_id: str, tenant_id: str = "default") -> dict[str, Any] | None:
        tenant = (tenant_id or "").strip() or "default"
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM astral_body_catalog WHERE body_id = ? AND tenant_id = ?",
                (body_id, tenant),
            ).fetchone()
            return dict(row) if row else None

    def astral_body_list(
        self,
        kind: str | None = None,
        tenant_id: str = "default",
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        tenant = (tenant_id or "").strip() or "default"
        with self._conn() as c:
            if kind:
                rows = c.execute(
                    "SELECT * FROM astral_body_catalog WHERE tenant_id = ? AND kind = ? ORDER BY body_id LIMIT ?",
                    (tenant, kind, limit),
                ).fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM astral_body_catalog WHERE tenant_id = ? ORDER BY body_id LIMIT ?",
                    (tenant, limit),
                ).fetchall()
            return [dict(r) for r in rows]

    # --- astral_observer_sites ---
    def astral_observer_site_insert(
        self,
        site_id: str,
        body_id: str,
        lat_deg: float,
        lon_deg: float,
        altitude_m: float = 0,
        reference_frame: str | None = None,
        tenant_id: str = "default",
    ) -> int:
        tenant = (tenant_id or "").strip() or "default"
        with self._conn() as c:
            cur = c.execute(
                """INSERT INTO astral_observer_sites
                   (site_id, body_id, lat_deg, lon_deg, altitude_m, reference_frame, tenant_id, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
                (site_id, body_id, lat_deg, lon_deg, altitude_m, reference_frame, tenant),
            )
            c.commit()
            return cur.lastrowid

    def astral_observer_site_get(self, site_id: str, tenant_id: str = "default") -> dict[str, Any] | None:
        tenant = (tenant_id or "").strip() or "default"
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM astral_observer_sites WHERE site_id = ? AND tenant_id = ?",
                (site_id, tenant),
            ).fetchone()
            return dict(row) if row else None

    def astral_observer_site_list(
        self,
        body_id: str | None = None,
        tenant_id: str = "default",
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        tenant = (tenant_id or "").strip() or "default"
        with self._conn() as c:
            if body_id:
                rows = c.execute(
                    "SELECT * FROM astral_observer_sites WHERE tenant_id = ? AND body_id = ? ORDER BY site_id LIMIT ?",
                    (tenant, body_id, limit),
                ).fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM astral_observer_sites WHERE tenant_id = ? ORDER BY site_id LIMIT ?",
                    (tenant, limit),
                ).fetchall()
            return [dict(r) for r in rows]

    # --- nasa_file_registry ---
    def nasa_file_insert(
        self,
        file_type: str,
        local_path: str,
        source_url: str | None = None,
        checksum: str | None = None,
        valid_from: str | None = None,
        valid_to: str | None = None,
        format_version: str | None = None,
        tenant_id: str = "default",
    ) -> int:
        tenant = (tenant_id or "").strip() or "default"
        with self._conn() as c:
            cur = c.execute(
                """INSERT INTO nasa_file_registry
                   (file_type, source_url, local_path, checksum, valid_from, valid_to, format_version, tenant_id, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
                (file_type, source_url, local_path, checksum, valid_from, valid_to, format_version, tenant),
            )
            c.commit()
            return cur.lastrowid

    def nasa_file_get(self, file_id: int, tenant_id: str = "default") -> dict[str, Any] | None:
        tenant = (tenant_id or "").strip() or "default"
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM nasa_file_registry WHERE id = ? AND tenant_id = ?",
                (file_id, tenant),
            ).fetchone()
            return dict(row) if row else None

    def nasa_file_list(
        self,
        file_type: str | None = None,
        tenant_id: str = "default",
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        tenant = (tenant_id or "").strip() or "default"
        with self._conn() as c:
            if file_type:
                rows = c.execute(
                    "SELECT * FROM nasa_file_registry WHERE tenant_id = ? AND file_type = ? ORDER BY id DESC LIMIT ?",
                    (tenant, file_type, limit),
                ).fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM nasa_file_registry WHERE tenant_id = ? ORDER BY id DESC LIMIT ?",
                    (tenant, limit),
                ).fetchall()
            return [dict(r) for r in rows]

    # --- ephemeris_samples ---
    def ephemeris_sample_insert(
        self,
        body_id: str,
        epoch_utc: str,
        position_x: float,
        position_y: float,
        position_z: float,
        velocity_x: float | None = None,
        velocity_y: float | None = None,
        velocity_z: float | None = None,
        frame_id: str | None = None,
        source_file_id: int | None = None,
        tenant_id: str = "default",
    ) -> int:
        tenant = (tenant_id or "").strip() or "default"
        with self._conn() as c:
            cur = c.execute(
                """INSERT INTO ephemeris_samples
                   (body_id, epoch_utc, position_x, position_y, position_z, velocity_x, velocity_y, velocity_z,
                    frame_id, source_file_id, tenant_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (body_id, epoch_utc, position_x, position_y, position_z, velocity_x, velocity_y, velocity_z,
                 frame_id, source_file_id, tenant),
            )
            c.commit()
            return cur.lastrowid

    def ephemeris_sample_get(
        self,
        body_id: str,
        epoch_utc: str,
        tenant_id: str = "default",
    ) -> dict[str, Any] | None:
        tenant = (tenant_id or "").strip() or "default"
        with self._conn() as c:
            row = c.execute(
                """SELECT * FROM ephemeris_samples
                   WHERE body_id = ? AND epoch_utc = ? AND tenant_id = ?
                   ORDER BY id DESC LIMIT 1""",
                (body_id, epoch_utc, tenant),
            ).fetchone()
            return dict(row) if row else None

    def ephemeris_sample_list_near_epoch(
        self,
        body_id: str,
        epoch_utc: str,
        tenant_id: str = "default",
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        tenant = (tenant_id or "").strip() or "default"
        with self._conn() as c:
            rows = c.execute(
                """SELECT * FROM ephemeris_samples
                   WHERE body_id = ? AND tenant_id = ?
                   ORDER BY ABS(julianday(epoch_utc) - julianday(?)) ASC
                   LIMIT ?""",
                (body_id, tenant, epoch_utc, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    # --- occlusion_events ---
    def occlusion_event_insert(
        self,
        epoch_utc: str,
        source_body_id: str,
        target_body_id: str,
        occluder_body_id: str,
        occlusion_ratio: float | None = None,
        eclipse_type: str | None = None,
        tenant_id: str = "default",
    ) -> int:
        tenant = (tenant_id or "").strip() or "default"
        with self._conn() as c:
            cur = c.execute(
                """INSERT INTO occlusion_events
                   (epoch_utc, source_body_id, target_body_id, occluder_body_id, occlusion_ratio, eclipse_type, tenant_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (epoch_utc, source_body_id, target_body_id, occluder_body_id, occlusion_ratio, eclipse_type, tenant),
            )
            c.commit()
            return cur.lastrowid

    def occlusion_event_list(
        self,
        epoch_utc: str | None = None,
        target_body_id: str | None = None,
        tenant_id: str = "default",
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        tenant = (tenant_id or "").strip() or "default"
        with self._conn() as c:
            sql = "SELECT * FROM occlusion_events WHERE tenant_id = ?"
            params: list[Any] = [tenant]
            if epoch_utc:
                sql += " AND epoch_utc = ?"
                params.append(epoch_utc)
            if target_body_id:
                sql += " AND target_body_id = ?"
                params.append(target_body_id)
            sql += " ORDER BY id DESC LIMIT ?"
            params.append(limit)
            rows = c.execute(sql, params).fetchall()
            return [dict(r) for r in rows]

    # --- ingestion_jobs ---
    def ingestion_job_insert(
        self,
        job_type: str,
        source: str,
        payload_json: str | dict | None = None,
        status: str = "pending",
        tenant_id: str = "default",
    ) -> int:
        tenant = (tenant_id or "").strip() or "default"
        payload_str = json.dumps(payload_json) if isinstance(payload_json, dict) else payload_json
        with self._conn() as c:
            cur = c.execute(
                """INSERT INTO ingestion_jobs (job_type, source, status, payload_json, tenant_id, updated_at)
                   VALUES (?, ?, ?, ?, ?, datetime('now'))""",
                (job_type, source, status, payload_str, tenant),
            )
            c.commit()
            return cur.lastrowid

    def ingestion_job_start(self, job_id: int, tenant_id: str = "default") -> bool:
        tenant = (tenant_id or "").strip() or "default"
        with self._conn() as c:
            cur = c.execute(
                """UPDATE ingestion_jobs
                   SET status = 'running', started_at = COALESCE(started_at, datetime('now')),
                       attempt_count = attempt_count + 1, updated_at = datetime('now')
                   WHERE id = ? AND tenant_id = ? AND status IN ('pending','failed')""",
                (job_id, tenant),
            )
            c.commit()
            return cur.rowcount > 0

    def ingestion_job_complete(self, job_id: int, tenant_id: str = "default") -> None:
        tenant = (tenant_id or "").strip() or "default"
        with self._conn() as c:
            c.execute(
                """UPDATE ingestion_jobs
                   SET status = 'completed', finished_at = datetime('now'), error_text = NULL, updated_at = datetime('now')
                   WHERE id = ? AND tenant_id = ?""",
                (job_id, tenant),
            )
            c.commit()

    def ingestion_job_fail(self, job_id: int, error_text: str, tenant_id: str = "default") -> None:
        tenant = (tenant_id or "").strip() or "default"
        with self._conn() as c:
            c.execute(
                """UPDATE ingestion_jobs
                   SET status = 'failed', finished_at = datetime('now'), error_text = ?, updated_at = datetime('now')
                   WHERE id = ? AND tenant_id = ?""",
                (error_text, job_id, tenant),
            )
            c.commit()

    def ingestion_job_get(self, job_id: int, tenant_id: str = "default") -> dict[str, Any] | None:
        tenant = (tenant_id or "").strip() or "default"
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM ingestion_jobs WHERE id = ? AND tenant_id = ?",
                (job_id, tenant),
            ).fetchone()
            return dict(row) if row else None

    def ingestion_job_list(
        self,
        status: str | None = None,
        job_type: str | None = None,
        tenant_id: str = "default",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        tenant = (tenant_id or "").strip() or "default"
        with self._conn() as c:
            sql = "SELECT * FROM ingestion_jobs WHERE tenant_id = ?"
            params: list[Any] = [tenant]
            if status:
                sql += " AND status = ?"
                params.append(status)
            if job_type:
                sql += " AND job_type = ?"
                params.append(job_type)
            sql += " ORDER BY id DESC LIMIT ?"
            params.append(limit)
            rows = c.execute(sql, params).fetchall()
            return [dict(r) for r in rows]

    # --- raw SQL for explorer window ---
    def execute_read(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        """Run read-only SQL; returns list of row dicts."""
        with self._conn() as c:
            rows = c.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
