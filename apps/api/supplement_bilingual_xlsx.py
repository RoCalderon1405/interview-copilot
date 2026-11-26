"""Prepare or explicitly apply one reviewed bilingual supplement XLSX offline.

Preparation is read-only for the active database and creates a private snapshot.
Apply requires a reviewed token, a stopped backend/capture and a fresh verified
backup. There is no HTTP endpoint, model call, download or automatic indexing.
"""
from __future__ import annotations

import argparse
import json
import socket
import sqlite3
import zipfile
from pathlib import Path

from openpyxl.utils.exceptions import InvalidFileException

from app.incremental_supplement import SupplementError, apply_supplement, prepare_supplement

DEFAULT_PORT = 8765


def _port_is_listening(port: int = DEFAULT_PORT) -> bool:
    try:
        connection = socket.create_connection(("127.0.0.1", port), timeout=0.5)
    except OSError:
        return False
    connection.close()
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True,
                        help="Existing copilot.sqlite3; never creates or migrates a database")
    parser.add_argument("--document-id", help="Existing canonical eight-sheet XLSX document ID")
    parser.add_argument("--candidate", type=Path, help="Reviewed full workbook containing the one MSG-012 row")
    parser.add_argument("--candidate-sha256", help="Required reviewed candidate SHA-256")
    parser.add_argument("--row-id", default="MSG-012", help="Reviewed workbook row ID")
    parser.add_argument("--output-dir", type=Path, help="New unique private directory outside the repository/data root")
    parser.add_argument("--prepared-dir", type=Path, help="Preparation directory created by the read-only dry-run")
    parser.add_argument("--apply", action="store_true", help="Apply the reviewed supplement; creates a fresh backup first")
    parser.add_argument("--reviewed-token", help="Exact preview_token from the reviewed preparation")
    parser.add_argument("--backend-stopped", action="store_true",
                        help="Confirm capture and every backend process are stopped normally")
    args = parser.parse_args()

    if args.apply:
        if not args.prepared_dir or not args.reviewed_token or not args.backend_stopped:
            parser.error("--apply requires --prepared-dir, --reviewed-token and --backend-stopped")
        if args.document_id or args.candidate or args.candidate_sha256 or args.output_dir:
            parser.error("Preparation arguments are not valid with --apply")
        if _port_is_listening():
            parser.error("Port 8765 is still listening. Stop capture/backend normally before applying.")
    else:
        if not args.document_id or not args.candidate or not args.output_dir or not args.candidate_sha256:
            parser.error("Preparation requires --document-id, --candidate, --candidate-sha256 and --output-dir")
        if args.prepared_dir or args.reviewed_token or args.backend_stopped:
            parser.error("Apply arguments are only valid with --apply")

    try:
        if args.apply:
            result = apply_supplement(args.database, args.prepared_dir, args.reviewed_token,
                                      backend_stopped=args.backend_stopped)
        else:
            result = prepare_supplement(args.database, args.document_id, args.candidate, args.output_dir,
                                        expected_candidate_sha256=args.candidate_sha256, row_id=args.row_id)
    except SupplementError as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    except (OSError, sqlite3.Error, ValueError, KeyError, zipfile.BadZipFile, InvalidFileException):
        # Never echo source cells, Practice text or private filesystem exceptions.
        # Apply may raise after a committed transaction, so never claim no changes there.
        message = ("Supplement apply failed. Verify the prepared directory, its apply-backups and database "
                   "counts before retrying." if args.apply else
                   "Supplement preparation refused or failed. Verify the database, hashes, row ID, "
                   "collisions, prepared artifacts and output directory. No database changes were committed.")
        print(json.dumps({"error": message}))
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
