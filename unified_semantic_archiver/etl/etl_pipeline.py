"""
Luigi ETL pipeline stub: ExtractTask -> TransformTask (identity) -> LoadTask.
Mostly identity-transformed; stub for future compression/aggregation.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

import luigi

# Ensure parent package is on path when run as luigi --module etl.etl_pipeline
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR.parent.parent) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR.parent.parent))

from unified_semantic_archiver.db import ContinuumDb


class ExtractTask(luigi.Task):
    """Read from file path; output to LocalTarget."""

    source_path = luigi.Parameter(default="./input/")
    db_path = luigi.Parameter(default="./continuum.db")

    def output(self):
        return luigi.LocalTarget(Path(self.source_path) / ".etl_extract_done")

    def run(self):
        source = Path(self.source_path)
        source.mkdir(parents=True, exist_ok=True)
        files = list(source.glob("*"))
        # Exclude our own marker and hidden
        files = [f for f in files if f.name != ".etl_extract_done" and not f.name.startswith(".")]
        data = {
            "files": [str(f.relative_to(source) if source != Path(".") else f.name) for f in files],
            "source_path": str(source.resolve()),
            "extracted_at": datetime.utcnow().isoformat() + "Z",
        }
        out_dir = self.output().path
        Path(out_dir).parent.mkdir(parents=True, exist_ok=True)
        extract_out = Path(self.source_path) / ".etl_extract.json"
        extract_out.write_text(json.dumps(data, indent=2), encoding="utf-8")
        Path(self.output().path).touch()


class TransformTask(luigi.Task):
    """Identity transform: pass data through with optional metadata."""

    source_path = luigi.Parameter(default="./input/")
    db_path = luigi.Parameter(default="./continuum.db")

    def requires(self):
        return ExtractTask(source_path=self.source_path, db_path=self.db_path)

    def output(self):
        return luigi.LocalTarget(Path(self.source_path) / ".etl_transform_done")

    def run(self):
        extract_json = Path(self.source_path) / ".etl_extract.json"
        if not extract_json.exists():
            # Extract may have produced nothing; create minimal payload
            data = {"files": [], "source_path": str(Path(self.source_path).resolve()), "extracted_at": datetime.utcnow().isoformat() + "Z"}
        else:
            data = json.loads(extract_json.read_text(encoding="utf-8"))
        # Identity: add metadata
        data["ingested_at"] = datetime.utcnow().isoformat() + "Z"
        content = json.dumps(data, sort_keys=True)
        data["checksum"] = hashlib.sha256(content.encode()).hexdigest()
        transform_out = Path(self.source_path) / ".etl_transform.json"
        transform_out.write_text(json.dumps(data, indent=2), encoding="utf-8")
        Path(self.output().path).touch()


class LoadTask(luigi.Task):
    """Load transformed data into continuum DB or file staging."""

    source_path = luigi.Parameter(default="./input/")
    db_path = luigi.Parameter(default="./continuum.db")

    def requires(self):
        return TransformTask(source_path=self.source_path, db_path=self.db_path)

    def output(self):
        return luigi.LocalTarget(Path(self.source_path) / ".etl_load_done")

    def run(self):
        transform_json = Path(self.source_path) / ".etl_transform.json"
        if not transform_json.exists():
            Path(self.output().path).touch()
            return
        data = json.loads(transform_json.read_text(encoding="utf-8"))
        db = ContinuumDb(self.db_path)
        # Store metadata in continuum_meta
        db.meta_set("etl_last_source", data.get("source_path", ""))
        db.meta_set("etl_last_checksum", data.get("checksum", ""))
        db.meta_set("etl_last_ingested", data.get("ingested_at", ""))
        # Optionally insert document_blobs for each file (stub: just record path)
        for f in data.get("files", []):
            full_path = str(Path(self.source_path) / f)
            db.document_blob_insert(tar_hash=data.get("checksum", ""), path=full_path, mime_type=None)
        Path(self.output().path).touch()


if __name__ == "__main__":
    luigi.run()
