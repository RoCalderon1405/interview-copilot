"""Preview or explicitly repair the existing eight-sheet bilingual XLSX offline."""
from __future__ import annotations

import argparse
import json
import socket
import sqlite3
from pathlib import Path

from app.bilingual_reprocess import apply_reprocess, preview_reprocess


def main() -> int:
    """Require an explicit database/document and reviewed preview token before writing."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True, help="Existing copilot.sqlite3; never creates a database")
    parser.add_argument("--document-id", required=True)
    parser.add_argument("--apply", action="store_true", help="Apply the reviewed preview; creates a backup first")
    parser.add_argument("--preview-token", help="Exact token from the latest dry-run")
    parser.add_argument("--backend-stopped", action="store_true", help="Confirm capture/backend are stopped normally")
    args = parser.parse_args()
    if args.apply and (not args.preview_token or not args.backend_stopped):
        parser.error("--apply requires --preview-token and explicit --backend-stopped confirmation")
    if not args.apply and (args.preview_token or args.backend_stopped):
        parser.error("Confirmation arguments are only valid with --apply")
    if args.apply:
        try:
            connection = socket.create_connection(("127.0.0.1", 8765), timeout=0.5)
        except OSError:
            pass
        else:
            connection.close()
            parser.error("Port 8765 is still listening. Stop capture/backend normally before applying.")
    try:
        result = (apply_reprocess(args.database, args.document_id, args.preview_token) if args.apply
                  else preview_reprocess(args.database, args.document_id))
    except (ValueError, OSError, sqlite3.Error):
        # Do not print source cells, Practice text or private filesystem exceptions.
        print(json.dumps({"error": "Reprocessing refused or failed. Verify the source/hash, documented format, idle indexing and latest preview. No partial entry changes were committed."}))
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
