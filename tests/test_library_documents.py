"""
Smoke tests for USC library_document_* API (insert and search with tenant_id).
"""
import tempfile
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
    Path(path).unlink(missing_ok=True)


def test_library_document_insert_and_search(temp_db):
    db = ContinuumDb(temp_db)
    doc_id = db.library_document_insert(
        document_type="document",
        type_metadata={"title": "Test"},
        tenant_id="default",
    )
    assert doc_id is not None
    assert doc_id >= 1

    rows = db.library_document_search(tenant_id="default", limit=10)
    assert len(rows) >= 1
    found = next((r for r in rows if r["id"] == doc_id), None)
    assert found is not None
    assert found["document_type"] == "document"
    assert found["tenant_id"] == "default"


def test_library_document_get_scoped_by_tenant(temp_db):
    db = ContinuumDb(temp_db)
    doc_id = db.library_document_insert(
        document_type="video",
        tenant_id="team-a",
    )
    assert db.library_document_get(doc_id, tenant_id="team-a") is not None
    assert db.library_document_get(doc_id, tenant_id="team-b") is None
