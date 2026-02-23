"""
NASA flat-file ingestion: register, validate checksum/coverage, ingest into USC schema.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from unified_semantic_archiver.db import ContinuumDb


@dataclass
class IngestionResult:
    job_id: int
    status: str
    samples_inserted: int
    error_text: str | None = None


def _file_checksum(path: Path, algorithm: str = "sha256") -> str:
    h = hashlib.new(algorithm)
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _parse_horizons_vectors(path: Path, body_id: str = "earth") -> list[dict[str, Any]]:
    """Parse JPL Horizons $$SOE ... $$EOE vector blocks."""
    text = path.read_text(encoding="utf-8", errors="replace")
    samples = []
    soe_blocks = re.findall(r"\$\$SOE\s+(.*?)\s+\$\$EOE", text, re.DOTALL | re.IGNORECASE)
    for block in soe_blocks:
        epoch_match = re.search(
            r"(\d+\.?\d*)\s*=\s*(A\.D\.\s+\d{4}-\w{3}-\d{1,2}\s+\d{2}:\d{2}:\d{2}[^\s]*)",
            block,
        )
        pos_match = re.search(
            r"X\s*=\s*([-\d.Ee+]+)\s+Y\s*=\s*([-\d.Ee+]+)\s+Z\s*=\s*([-\d.Ee+]+)",
            block,
        )
        vel_match = re.search(
            r"VX\s*=\s*([-\d.Ee+]+)\s+VY\s*=\s*([-\d.Ee+]+)\s+VZ\s*=\s*([-\d.Ee+]+)",
            block,
        )
        if epoch_match and pos_match and vel_match:
            months = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
                      "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12}
            epoch_str = epoch_match.group(2).strip()
            m = re.search(r"A\.D\.\s+(\d{4})-(\w{3})-(\d{1,2})\s+(\d{2}):(\d{2}):(\d{2})", epoch_str)
            if m:
                y, mon_str, d, hh, mm, ss = m.groups()
                mon = months.get(mon_str, 1)
                from datetime import datetime, timezone
                dt = datetime(int(y), mon, int(d), int(hh), int(mm), int(ss), tzinfo=timezone.utc)
                epoch_utc = dt.strftime("%Y-%m-%dT%H:%M:%S")
            else:
                epoch_utc = epoch_str
            samples.append({
                "body_id": body_id,
                "epoch_utc": epoch_utc,
                "position_x": float(pos_match.group(1)),
                "position_y": float(pos_match.group(2)),
                "position_z": float(pos_match.group(3)),
                "velocity_x": float(vel_match.group(1)),
                "velocity_y": float(vel_match.group(2)),
                "velocity_z": float(vel_match.group(3)),
            })
    return samples


def _infer_coverage_from_samples(samples: list[dict]) -> tuple[str | None, str | None]:
    """Infer valid_from/valid_to from sample epochs."""
    if not samples:
        return None, None
    epochs = sorted(s["epoch_utc"] for s in samples)
    return epochs[0], epochs[-1]


class NasaIngestionRunner:
    """Register NASA files, validate, and ingest into USC schema."""

    def __init__(self, db: ContinuumDb, tenant_id: str = "default"):
        self.db = db
        self.tenant_id = tenant_id

    def register_file(
        self,
        file_type: str,
        local_path: str | Path,
        source_url: str | None = None,
        checksum: str | None = None,
        valid_from: str | None = None,
        valid_to: str | None = None,
        format_version: str | None = None,
    ) -> int:
        """Register a NASA kernel/file. Computes checksum if not provided."""
        path = Path(local_path)
        if not path.is_file():
            raise FileNotFoundError(f"File not found: {path}")
        if file_type not in ("spk", "pck", "lsk", "fk", "horizons"):
            raise ValueError(f"Invalid file_type: {file_type}")
        computed = _file_checksum(path) if checksum is None else checksum
        return self.db.nasa_file_insert(
            file_type=file_type,
            local_path=str(path.resolve()),
            source_url=source_url,
            checksum=computed,
            valid_from=valid_from,
            valid_to=valid_to,
            format_version=format_version,
            tenant_id=self.tenant_id,
        )

    def validate_checksum(self, file_id: int) -> bool:
        """Verify stored checksum matches file on disk."""
        row = self.db.nasa_file_get(file_id, self.tenant_id)
        if not row or not row.get("local_path"):
            return False
        path = Path(row["local_path"])
        if not path.is_file():
            return False
        stored = row.get("checksum") or ""
        computed = _file_checksum(path)
        return stored == computed

    def validate_coverage(self, file_id: int) -> dict[str, Any]:
        """Return coverage info. For horizons, parses file. For binary kernels, returns registry values."""
        row = self.db.nasa_file_get(file_id, self.tenant_id)
        if not row:
            return {"valid": False, "error": "file not found"}
        path = Path(row.get("local_path", ""))
        if not path.is_file():
            return {"valid": False, "error": "file not on disk"}
        ft = row.get("file_type", "")
        if ft == "horizons":
            try:
                samples = _parse_horizons_vectors(path)
                valid_from, valid_to = _infer_coverage_from_samples(samples)
                return {
                    "valid": True,
                    "sample_count": len(samples),
                    "valid_from": valid_from or row.get("valid_from"),
                    "valid_to": valid_to or row.get("valid_to"),
                }
            except Exception as e:
                return {"valid": False, "error": str(e)}
        return {
            "valid": True,
            "valid_from": row.get("valid_from"),
            "valid_to": row.get("valid_to"),
        }

    def run_ingestion_job(self, job_id: int, body_id: str = "earth") -> IngestionResult:
        """
        Run ingestion job: load file, parse, insert ephemeris_samples.
        Updates job status via ingestion_job_start/complete/fail.
        """
        if not self.db.ingestion_job_start(job_id, self.tenant_id):
            job = self.db.ingestion_job_get(job_id, self.tenant_id)
            status = job.get("status", "unknown") if job else "not_found"
            return IngestionResult(job_id=job_id, status=status, samples_inserted=0, error_text="Job not startable")
        job = self.db.ingestion_job_get(job_id, self.tenant_id)
        if not job:
            self.db.ingestion_job_fail(job_id, "Job record not found", self.tenant_id)
            return IngestionResult(job_id=job_id, status="failed", samples_inserted=0, error_text="Job record not found")
        payload = job.get("payload_json")
        if isinstance(payload, str):
            try:
                payload = json.loads(payload) if payload else {}
            except json.JSONDecodeError:
                payload = {}
        source = (payload.get("source") or job.get("source") or "").strip()
        file_id = payload.get("file_id")
        bid = (payload.get("body_id") or body_id).strip() or "earth"
        if not source:
            self.db.ingestion_job_fail(job_id, "Missing source path in payload", self.tenant_id)
            return IngestionResult(job_id=job_id, status="failed", samples_inserted=0, error_text="Missing source")
        path = Path(source)
        if not path.is_file():
            self.db.ingestion_job_fail(job_id, f"File not found: {path}", self.tenant_id)
            return IngestionResult(job_id=job_id, status="failed", samples_inserted=0, error_text=f"File not found: {path}")
        try:
            samples = _parse_horizons_vectors(path, body_id=bid)
            if not samples:
                self.db.ingestion_job_complete(job_id, self.tenant_id)
                return IngestionResult(job_id=job_id, status="completed", samples_inserted=0)
            source_file_id = file_id
            if source_file_id is None:
                reg = self.db.nasa_file_list(file_type="horizons", tenant_id=self.tenant_id, limit=1)
                for r in reg:
                    if r.get("local_path") == str(path.resolve()):
                        source_file_id = r["id"]
                        break
            count = 0
            for s in samples:
                self.db.ephemeris_sample_insert(
                    body_id=s["body_id"],
                    epoch_utc=s["epoch_utc"],
                    position_x=s["position_x"],
                    position_y=s["position_y"],
                    position_z=s["position_z"],
                    velocity_x=s.get("velocity_x"),
                    velocity_y=s.get("velocity_y"),
                    velocity_z=s.get("velocity_z"),
                    frame_id="J2000",
                    source_file_id=source_file_id,
                    tenant_id=self.tenant_id,
                )
                count += 1
            valid_from, valid_to = _infer_coverage_from_samples(samples)
            if source_file_id and (valid_from or valid_to):
                # Update registry coverage if we have it
                pass  # continuum_db doesn't have nasa_file_update; skip for now
            self.db.ingestion_job_complete(job_id, self.tenant_id)
            return IngestionResult(job_id=job_id, status="completed", samples_inserted=count)
        except Exception as e:
            self.db.ingestion_job_fail(job_id, str(e), self.tenant_id)
            return IngestionResult(job_id=job_id, status="failed", samples_inserted=0, error_text=str(e))
