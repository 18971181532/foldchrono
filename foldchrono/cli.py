"""Command-line interface for FoldChrono."""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from . import __version__
from .core import take_snapshot, tree_signature
from .diff import diff_snapshots, diff_working_tree
from .restore import restore
from .storage import Storage

# --------------------------------------------------------------------- helpers


def _fmt_size(n: int) -> str:
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if n < 1024 or unit == "TiB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n} B"


def _fmt_time(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return iso


def _resolve_path(arg: Optional[str]) -> Path:
    return Path(arg).resolve() if arg else Path.cwd().resolve()


def _latest_snapshot_id(storage: Storage, path: Path) -> Optional[int]:
    with storage._conn() as c:
        row = c.execute(
            "SELECT id FROM snapshots WHERE path = ? ORDER BY id DESC LIMIT 1",
            (str(path),),
        ).fetchone()
    return row[0] if row else None


def _require_snapshot(storage: Storage, sid: int) -> dict:
    with storage._conn() as c:
        row = c.execute(
            "SELECT id, path, created_at, comment, file_count, total_size"
            " FROM snapshots WHERE id = ?",
            (sid,),
        ).fetchone()
    if not row:
        raise SystemExit(f"error: snapshot #{sid} does not exist")
    return {
        "id": row[0],
        "path": row[1],
        "created_at": row[2],
        "comment": row[3],
        "file_count": row[4],
        "total_size": row[5],
    }


# --------------------------------------------------------------------- actions


def cmd_snapshot(args: argparse.Namespace, storage: Storage) -> int:
    path = _resolve_path(args.path)
    sid = take_snapshot(storage, path, comment=args.message)
    snap = _require_snapshot(storage, sid)
    print(
        f"Snapshot #{sid} created  "
        f"({snap['file_count']} files, {_fmt_size(snap['total_size'])})"
    )
    print(f"  path: {snap['path']}")
    print(f"  time: {_fmt_time(snap['created_at'])}")
    return 0


def cmd_list(args: argparse.Namespace, storage: Storage) -> int:
    path = _resolve_path(args.path) if args.path else None
    with storage._conn() as c:
        if path:
            rows = c.execute(
                "SELECT id, path, created_at, comment, file_count, total_size"
                " FROM snapshots WHERE path = ? ORDER BY id DESC",
                (str(path),),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT id, path, created_at, comment, file_count, total_size"
                " FROM snapshots ORDER BY id DESC"
            ).fetchall()
    if not rows:
        print("No snapshots yet.")
        return 0
    print(f"{'ID':<5}  {'DATE':<19}  {'FILES':>6}  {'SIZE':>9}  PATH / COMMENT")
    print("-" * 78)
    for sid, p, created, comment, fc, ts in rows:
        line = f"#{sid:<4}  {_fmt_time(created):<19}  {fc:>6}  {_fmt_size(ts):>9}  {p}"
        if comment:
            line += f"\n{'':>4}  {'':<19}  {'':>6}  {'':>9}  ↳ {comment}"
        print(line)
    return 0


def cmd_show(args: argparse.Namespace, storage: Storage) -> int:
    snap = _require_snapshot(storage, args.id)
    print(f"Snapshot #{snap['id']}")
    print(f"  path:      {snap['path']}")
    print(f"  created:   {_fmt_time(snap['created_at'])}")
    print(f"  comment:   {snap['comment'] or '(none)'}")
    print(f"  files:     {snap['file_count']}")
    print(f"  total:     {_fmt_size(snap['total_size'])}")
    with storage._conn() as c:
        rows = c.execute(
            "SELECT rel_path, size, sha256 FROM files WHERE snapshot_id = ?"
            " ORDER BY rel_path",
            (args.id,),
        ).fetchall()
    if rows:
        print(f"\n  {'SIZE':>9}  PATH")
        print(f"  {'-'*9}  {'-'*40}")
        for rel, size, _sha in rows:
            print(f"  {_fmt_size(size):>9}  {rel}")
    return 0


def cmd_diff(args: argparse.Namespace, storage: Storage) -> int:
    path = _resolve_path(args.path)

    if args.from_id is not None and args.to_id is not None:
        _require_snapshot(storage, args.from_id)
        _require_snapshot(storage, args.to_id)
        result = diff_snapshots(storage, args.from_id, args.to_id)
        label = f"#{args.from_id} -> #{args.to_id}"
    elif args.from_id is not None:
        _require_snapshot(storage, args.from_id)
        result = diff_working_tree(storage, args.from_id, path)
        label = f"#{args.from_id} -> working tree"
    else:
        latest = _latest_snapshot_id(storage, path)
        if latest is None:
            print(f"No snapshots for {path}. Run `foldchrono snapshot` first.")
            return 1
        result = diff_working_tree(storage, latest, path)
        label = f"#{latest} -> working tree"

    print(f"Diff {label}: {result.summary()}")
    if not result.has_changes:
        print("  (no changes)")
        return 0
    for p in result.added:
        print(f"  + {p}")
    for p in result.removed:
        print(f"  - {p}")
    for p in result.modified:
        print(f"  ~ {p}")
    return 0


def cmd_restore(args: argparse.Namespace, storage: Storage) -> int:
    snap = _require_snapshot(storage, args.id)
    if args.to:
        target = Path(args.to).resolve()
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        target = Path.cwd() / f"foldchrono_restore_{args.id}_{ts}"
    restored = restore(storage, args.id, target, file_pattern=args.file)
    print(f"Restored {len(restored)} file(s) from snapshot #{args.id}")
    print(f"  source snapshot path: {snap['path']}")
    print(f"  output directory:     {target}")
    if args.file:
        print(f"  filter:               {args.file}")
    if restored and args.verbose:
        for rel in restored:
            print(f"    {rel}")
    return 0


def cmd_rm(args: argparse.Namespace, storage: Storage) -> int:
    _require_snapshot(storage, args.id)
    with storage._conn() as c:
        c.execute("DELETE FROM snapshots WHERE id = ?", (args.id,))
    print(f"Snapshot #{args.id} deleted (run `foldchrono gc` to reclaim blobs).")
    return 0


def cmd_gc(args: argparse.Namespace, storage: Storage) -> int:
    removed, freed = storage.gc()
    print(f"Garbage collection: removed {removed} blob(s), freed {_fmt_size(freed)}.")
    return 0


def cmd_watch(args: argparse.Namespace, storage: Storage) -> int:
    path = _resolve_path(args.path)
    interval = max(1, args.interval)
    print(f"Watching {path} (every {interval}s). Press Ctrl+C to stop.")
    last_sig: Optional[str] = None
    try:
        while True:
            try:
                sig = tree_signature(path, storage)
            except (OSError, NotADirectoryError) as exc:
                print(f"[{datetime.now():%H:%M:%S}] error: {exc}", file=sys.stderr)
                time.sleep(interval)
                continue
            if sig != last_sig:
                sid = take_snapshot(storage, path, comment="auto (watch)")
                snap = _require_snapshot(storage, sid)
                print(
                    f"[{datetime.now():%H:%M:%S}] change detected — "
                    f"snapshot #{sid} ({snap['file_count']} files)"
                )
                last_sig = sig
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0


def cmd_status(args: argparse.Namespace, storage: Storage) -> int:
    path = _resolve_path(args.path)
    latest = _latest_snapshot_id(storage, path)
    if latest is None:
        print(f"No snapshots for {path}.")
        return 0
    result = diff_working_tree(storage, latest, path)
    print(f"Compared to snapshot #{latest}: {result.summary()}")
    if not result.has_changes:
        print("  working tree is clean.")
    else:
        for p in result.added:
            print(f"  + {p}")
        for p in result.removed:
            print(f"  - {p}")
        for p in result.modified:
            print(f"  ~ {p}")
    return 0


def cmd_log(args: argparse.Namespace, storage: Storage) -> int:
    """Show per-file history across all snapshots of a directory."""
    path = _resolve_path(args.path)
    file_rel = Path(args.file).as_posix()
    with storage._conn() as c:
        rows = c.execute(
            """
            SELECT s.id, s.created_at, s.comment, f.size, f.sha256
            FROM files f
            JOIN snapshots s ON f.snapshot_id = s.id
            WHERE s.path = ? AND f.rel_path = ?
            ORDER BY s.id ASC
            """,
            (str(path), file_rel),
        ).fetchall()
    if not rows:
        print(f"No history for '{file_rel}' under {path}")
        return 1
    print(f"History of {file_rel}:")
    print(f"  {'SNAPSHOT':<9} {'DATE':<19} {'SIZE':>9}  CHANGE")
    print(f"  {'-'*9} {'-'*19} {'-'*9}  {'-'*8}")
    prev_sha = None
    for sid, created, comment, size, sha in rows:
        if prev_sha is None:
            change = "added"
        elif prev_sha != sha:
            change = "modified"
        else:
            change = "unchanged"
        print(f"  #{sid:<8} {_fmt_time(created):<19} {_fmt_size(size):>9}  {change}")
        if comment:
            print(f"  {'':<9} {'':<19} {'':>9}  ↳ {comment}")
        prev_sha = sha
    return 0


# --------------------------------------------------------------------- parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="foldchrono",
        description=(
            "Local-first directory time capsule — snapshot, diff, and restore "
            "any folder without git. Content-addressed deduplication keeps "
            "history compact."
        ),
    )
    parser.add_argument(
        "--data-dir",
        help="Override the storage directory (default: ~/.foldchrono)",
    )
    parser.add_argument(
        "--version", action="version", version=f"foldchrono {__version__}"
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    # snapshot
    p = sub.add_parser("snapshot", help="Record the current state of a directory")
    p.add_argument("path", nargs="?", help="Directory to snapshot (default: cwd)")
    p.add_argument("-m", "--message", help="Optional comment for this snapshot")
    p.set_defaults(func=cmd_snapshot)

    # list
    p = sub.add_parser("list", help="List snapshots (optionally for one path)")
    p.add_argument("path", nargs="?", help="Filter by directory path")
    p.set_defaults(func=cmd_list)

    # show
    p = sub.add_parser("show", help="Show details and file list of a snapshot")
    p.add_argument("id", type=int, help="Snapshot ID")
    p.set_defaults(func=cmd_show)

    # diff
    p = sub.add_parser("diff", help="Show changes between snapshots / working tree")
    p.add_argument("path", nargs="?", help="Directory (default: cwd)")
    p.add_argument("--from", dest="from_id", type=int, help="From snapshot ID")
    p.add_argument("--to", dest="to_id", type=int, help="To snapshot ID")
    p.set_defaults(func=cmd_diff)

    # restore
    p = sub.add_parser("restore", help="Restore files from a snapshot to a directory")
    p.add_argument("id", type=int, help="Snapshot ID to restore from")
    p.add_argument("--to", help="Output directory (default: ./foldchrono_restore_<id>_<ts>)")
    p.add_argument("--file", help="Only restore files matching this glob pattern")
    p.add_argument("-v", "--verbose", action="store_true", help="List every restored file")
    p.set_defaults(func=cmd_restore)

    # rm
    p = sub.add_parser("rm", help="Delete a snapshot (metadata only; run gc to free blobs)")
    p.add_argument("id", type=int, help="Snapshot ID to delete")
    p.set_defaults(func=cmd_rm)

    # gc
    p = sub.add_parser("gc", help="Remove unreferenced blobs to reclaim disk space")
    p.set_defaults(func=cmd_gc)

    # watch
    p = sub.add_parser("watch", help="Continuously snapshot on change")
    p.add_argument("path", nargs="?", help="Directory to watch (default: cwd)")
    p.add_argument("-i", "--interval", type=int, default=30, help="Poll interval in seconds (default: 30)")
    p.set_defaults(func=cmd_watch)

    # status
    p = sub.add_parser("status", help="Show changes since the latest snapshot")
    p.add_argument("path", nargs="?", help="Directory (default: cwd)")
    p.set_defaults(func=cmd_status)

    # log
    p = sub.add_parser("log", help="Show change history of a single file across snapshots")
    p.add_argument("file", help="Relative path of the file to inspect")
    p.add_argument("path", nargs="?", help="Directory that was snapshotted (default: cwd)")
    p.set_defaults(func=cmd_log)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 1
    storage = Storage(data_dir=args.data_dir)
    try:
        return args.func(args, storage)
    except SystemExit as e:
        if isinstance(e.code, int):
            return e.code
        print(str(e.code), file=sys.stderr)
        return 1
    except (NotADirectoryError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
