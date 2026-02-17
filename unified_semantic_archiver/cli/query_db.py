"""
CLI to query continuum DB and output JSON for Unity explorer.
Usage: python -m unified_semantic_archiver.cli.query_db --db path/to/continuum.db --table spatial_4d
       python -m unified_semantic_archiver.cli.query_db --db path --table library_documents --lat 40.7 --lon -74 --distance_mi 10
       python -m unified_semantic_archiver.cli.query_db --db path --sql-file /tmp/query.sql
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure package on path (parent of Scripts)
_script_dir = Path(__file__).resolve().parent
_repo_root = _script_dir.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from unified_semantic_archiver.db import ContinuumDb


def _row_to_json_serializable(r: dict) -> dict:
    out = {}
    for k, v in r.items():
        if hasattr(v, "isoformat"):
            out[k] = v.isoformat() if v else None
        else:
            out[k] = v
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True, help="Path to continuum.db")
    ap.add_argument(
        "--table",
        help="Table name: spatial_4d, document_blobs, semantic_chunks, unique_kernels, compression_runs, research_suggestions, continuum_meta, library_documents",
    )
    ap.add_argument("--sql", help="Raw SELECT (read-only)")
    ap.add_argument("--sql-file", help="Path to file containing SELECT query")
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--lat", type=float, help="Latitude for library_documents search")
    ap.add_argument("--lon", type=float, help="Longitude for library_documents search")
    ap.add_argument("--distance_mi", help="Miles for location filter: 0=same bucket, number, or 'infinite'")
    ap.add_argument("--document_type", help="Filter library_documents by type (video, document, audio, image, program, data)")
    ap.add_argument("-q", "--query", dest="q", help="Text search in library_documents (type_metadata, url)")
    ap.add_argument("--tenant", default="default", help="Tenant id for library_documents (default: default)")
    args = ap.parse_args()

    db = ContinuumDb(args.db)

    sql_query = args.sql
    if args.sql_file:
        sql_query = Path(args.sql_file).read_text(encoding="utf-8").strip()

    if sql_query:
        rows = db.execute_read(sql_query)
    elif args.table:
        table = args.table.lower()
        if table == "spatial_4d":
            rows = db.spatial_4d_list(limit=args.limit)
        elif table == "document_blobs":
            rows = db.document_blob_list(limit=args.limit)
        elif table == "semantic_chunks":
            rows = db.semantic_chunk_list(limit=args.limit)
        elif table == "unique_kernels":
            rows = db.unique_kernel_list(limit=args.limit)
        elif table == "compression_runs":
            rows = db.compression_run_list(limit=args.limit)
        elif table == "research_suggestions":
            rows = db.research_suggestion_list(limit=args.limit)
        elif table == "continuum_meta":
            rows = db.execute_read("SELECT * FROM continuum_meta LIMIT ?", (args.limit,))
        elif table == "library_documents":
            distance_mi = args.distance_mi
            if distance_mi is None and (args.lat is not None or args.lon is not None):
                distance_mi = "infinite"
            rows = db.library_document_search(
                document_type=args.document_type,
                q=args.q,
                lat=args.lat,
                lon=args.lon,
                distance_mi=distance_mi,
                tenant_id=args.tenant,
                limit=args.limit,
            )
        else:
            print(json.dumps({"error": f"Unknown table: {args.table}"}))
            return 1
    else:
        print(json.dumps({"error": "Provide --table, --sql, or --sql-file"}))
        return 1

    out = [_row_to_json_serializable(r) for r in rows]
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
