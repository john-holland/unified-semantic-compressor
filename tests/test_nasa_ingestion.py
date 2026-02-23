"""
Tests for NASA flat-file ingestion.
"""
import tempfile
import time
from pathlib import Path

import pytest

from unified_semantic_archiver.db import ContinuumDb, get_connection, init_schema
from unified_semantic_archiver.etl import NasaIngestionRunner
from unified_semantic_archiver.etl.nasa_ingestion import _parse_horizons_vectors


HORIZONS_SAMPLE = r"""
$$SOE
 2451545.00000000 = A.D. 2000-Jan-01 12:00:00.0000 TDB
  X = -2.648865568995978E-01  Y =  9.437477927642869E-01  Z =  3.637431804599647E-04
  VX= -1.613823890234401E-02  VY= -4.602245245109238E-03  VZ=  6.774557937097239E-07
$$EOE
$$SOE
 2451546.00000000 = A.D. 2000-Jan-02 12:00:00.0000 TDB
  X = -2.650381360283664E-01  Y =  9.436696506789992E-01  Z =  3.871027393796566E-04
  VX= -1.613418903592888E-02  VY= -4.603589290724059E-03  VZ=  6.513800428141696E-07
$$EOE
"""


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


@pytest.fixture
def horizons_file(tmp_path):
    p = tmp_path / "horizons_sample.txt"
    p.write_text(HORIZONS_SAMPLE)
    return p


def test_parse_horizons_vectors(horizons_file):
    samples = _parse_horizons_vectors(horizons_file, "earth")
    assert len(samples) == 2
    assert samples[0]["body_id"] == "earth"
    assert "position_x" in samples[0]
    assert abs(samples[0]["position_x"] - (-0.2648865568995978)) < 1e-6
    assert samples[0]["epoch_utc"].startswith("2000")


def test_nasa_ingestion_register_and_validate(temp_db, horizons_file):
    db = ContinuumDb(temp_db)
    runner = NasaIngestionRunner(db, "default")
    fid = runner.register_file("horizons", horizons_file)
    assert fid >= 1
    assert runner.validate_checksum(fid) is True
    cov = runner.validate_coverage(fid)
    assert cov["valid"] is True
    assert cov["sample_count"] == 2


def test_nasa_ingestion_run_job(temp_db, horizons_file):
    db = ContinuumDb(temp_db)
    runner = NasaIngestionRunner(db, "default")
    job_id = db.ingestion_job_insert(
        job_type="horizons",
        source=str(horizons_file.resolve()),
        payload_json={"source": str(horizons_file.resolve()), "body_id": "earth"},
        tenant_id="default",
    )
    result = runner.run_ingestion_job(job_id, "earth")
    assert result.status == "completed"
    assert result.samples_inserted == 2
    row = db.ephemeris_sample_get("earth", "2000-01-01T12:00:00", "default")
    assert row is not None
