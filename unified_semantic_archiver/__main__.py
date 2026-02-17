"""
CLI entrypoint for Unified Semantic Archiver.
Usage:
  python -m unified_semantic_archiver init --db ./continuum.db
  python -m unified_semantic_archiver run-etl --source ./input/ --db ./continuum.db
  python -m unified_semantic_archiver compress --media path.mp4 --type video --out ./out --db ./continuum.db
  python -m unified_semantic_archiver cursor-research --db ./continuum.db
"""

import argparse
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(prog="unified_semantic_archiver")
    sub = ap.add_subparsers(dest="cmd", required=True)

    # init
    p_init = sub.add_parser("init", help="Initialize continuum DB schema")
    p_init.add_argument("--db", default="./continuum.db", help="DB path")
    p_init.set_defaults(func=cmd_init)

    # run-etl
    p_etl = sub.add_parser("run-etl", help="Run Luigi ETL pipeline")
    p_etl.add_argument("--source", default="./input/", help="Source directory")
    p_etl.add_argument("--db", default="./continuum.db", help="DB path")
    p_etl.set_defaults(func=cmd_etl)

    # compress
    p_compress = sub.add_parser("compress", help="Run compressor on media")
    p_compress.add_argument("--media", required=True, help="Path to video/audio/code/data")
    p_compress.add_argument("--type", choices=("video", "image", "audio", "library", "data"), required=True)
    p_compress.add_argument("--out", default="./compressed/", help="Output directory")
    p_compress.add_argument("--db", help="Continuum DB path (optional)")
    p_compress.set_defaults(func=cmd_compress)

    # cursor-research
    p_cursor = sub.add_parser("cursor-research", help="Build Cursor research context")
    p_cursor.add_argument("--db", default="./continuum.db", help="DB path")
    p_cursor.add_argument("--output", help="Output JSON path")
    p_cursor.set_defaults(func=cmd_cursor)

    args = ap.parse_args()
    return args.func(args)


def cmd_init(args) -> int:
    from unified_semantic_archiver.db import ContinuumDb, init_schema
    from unified_semantic_archiver.db.continuum_db import get_connection

    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = get_connection(db_path)
    init_schema(conn)
    conn.close()
    print(f"Initialized continuum DB at {db_path}")
    return 0


def cmd_etl(args) -> int:
    import luigi
    from unified_semantic_archiver.etl.etl_pipeline import LoadTask

    luigi.build([LoadTask(source_path=args.source, db_path=args.db)], local_scheduler=True)
    print("ETL complete.")
    return 0


def cmd_compress(args) -> int:
    from unified_semantic_archiver.compressors.ring_orchestrator import run_ring

    media_path = Path(args.media)
    if not media_path.exists():
        print(f"Error: {media_path} not found", file=sys.stderr)
        return 1
    out_dir = Path(args.out)
    db_path = Path(args.db) if args.db else None
    result = run_ring(media_path, args.type, out_dir, db_path=db_path)
    print("Compression result:", result)
    return 0


def cmd_cursor(args) -> int:
    from unified_semantic_archiver.services.cursor_call_service import invoke_cursor_workflow

    db_path = Path(args.db)
    out_path = Path(args.output) if args.output else None
    result = invoke_cursor_workflow(db_path, context_output_path=out_path)
    print("Context written to:", result["context_path"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
