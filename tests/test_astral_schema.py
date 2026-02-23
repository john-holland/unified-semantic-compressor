"""
Tests for astral schema tables and CRUD: astral_body_catalog, ephemeris_samples, ingestion_jobs, etc.
"""
import tempfile
import time
from pathlib import Path

import pytest

from unified_semantic_archiver.db import ContinuumDb, get_connection, init_schema


@pytest.fixture
def temp_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    conn = get_connection(path)
    init_schema(conn)
    conn.close()
    yield path
    db_path = Path(path)
    for _ in range(5):
        try:
            db_path.unlink(missing_ok=True)
            break
        except PermissionError:
            time.sleep(0.05)


def test_astral_body_crud(temp_db):
    db = ContinuumDb(temp_db)
    db.astral_body_insert(
        body_id="earth",
        name="Earth",
        kind="planet",
        mass_kg=5.97e24,
        radius_m=6.371e6,
        tenant_id="default",
    )
    row = db.astral_body_get("earth", "default")
    assert row is not None
    assert row["name"] == "Earth"
    assert row["kind"] == "planet"
    bodies = db.astral_body_list(kind="planet", tenant_id="default")
    assert len(bodies) >= 1
    assert any(b["body_id"] == "earth" for b in bodies)


def test_astral_observer_sites(temp_db):
    db = ContinuumDb(temp_db)
    db.astral_observer_site_insert(
        site_id="sea-tac",
        body_id="earth",
        lat_deg=47.45,
        lon_deg=-122.31,
        altitude_m=132.0,
        tenant_id="default",
    )
    row = db.astral_observer_site_get("sea-tac", "default")
    assert row is not None
    assert row["lat_deg"] == 47.45
    assert row["body_id"] == "earth"


def test_nasa_file_registry(temp_db):
    db = ContinuumDb(temp_db)
    fid = db.nasa_file_insert(
        file_type="horizons",
        local_path="/tmp/test_horizons.txt",
        checksum="abc123",
        valid_from="2020-01-01",
        valid_to="2030-01-01",
        tenant_id="default",
    )
    assert fid >= 1
    row = db.nasa_file_get(fid, "default")
    assert row is not None
    assert row["file_type"] == "horizons"
    assert row["checksum"] == "abc123"


def test_ephemeris_samples(temp_db):
    db = ContinuumDb(temp_db)
    db.ephemeris_sample_insert(
        body_id="earth",
        epoch_utc="2026-02-20T12:00:00",
        position_x=1.0,
        position_y=2.0,
        position_z=3.0,
        velocity_x=0.01,
        velocity_y=0.02,
        velocity_z=0.03,
        frame_id="J2000",
        tenant_id="default",
    )
    row = db.ephemeris_sample_get("earth", "2026-02-20T12:00:00", "default")
    assert row is not None
    assert row["position_x"] == 1.0
    assert row["position_z"] == 3.0


def test_occlusion_events(temp_db):
    db = ContinuumDb(temp_db)
    db.occlusion_event_insert(
        epoch_utc="2026-02-20T12:00:00",
        source_body_id="sun",
        target_body_id="earth",
        occluder_body_id="moon",
        occlusion_ratio=0.95,
        eclipse_type="planet_occludes_star",
        tenant_id="default",
    )
    rows = db.occlusion_event_list(epoch_utc="2026-02-20T12:00:00", tenant_id="default")
    assert len(rows) >= 1
    assert rows[0]["occluder_body_id"] == "moon"
    assert rows[0]["eclipse_type"] == "planet_occludes_star"


def test_ingestion_job_lifecycle(temp_db):
    db = ContinuumDb(temp_db)
    job_id = db.ingestion_job_insert(
        job_type="horizons",
        source="/tmp/horizons.txt",
        payload_json='{"body_id":"earth"}',
        status="pending",
        tenant_id="default",
    )
    assert job_id >= 1
    assert db.ingestion_job_start(job_id, "default") is True
    job = db.ingestion_job_get(job_id, "default")
    assert job["status"] == "running"
    db.ingestion_job_complete(job_id, "default")
    job = db.ingestion_job_get(job_id, "default")
    assert job["status"] == "completed"
    job_id2 = db.ingestion_job_insert(job_type="horizons", source="/tmp/x.txt", tenant_id="default")
    assert db.ingestion_job_start(job_id2, "default") is True
    db.ingestion_job_fail(job_id2, "File not found", "default")
    job2 = db.ingestion_job_get(job_id2, "default")
    assert job2["status"] == "failed"
    assert "File not found" in (job2.get("error_text") or "")
