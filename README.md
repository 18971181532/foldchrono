# FoldChrono ⏳

![Tests](https://github.com/18971181532/foldchrono/actions/workflows/test.yml/badge.svg)
![Python](https://img.shields.io/badge/python-3.9%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

> **Local-first directory time capsule** — snapshot, diff, and restore *any* folder, no git required.

FoldChrono gives your ordinary directories the same "time travel" superpower that version control gives code repos. Point it at a folder, take a snapshot, and later you can see exactly what changed, or bring back a file you deleted by accident — even if you never committed anything to git.

Under the hood it uses **content-addressed deduplication** (like git's object store): every unique file body is stored exactly once, so keeping dozens of snapshots of a large project costs barely more than one copy.

---

## Why not just use git?

| | git | FoldChrono |
|---|---|---|
| Works on non-code folders (photos, docs, game saves) | ❌ clunky | ✅ first-class |
| Zero setup (`init`, `.gitignore`, remotes) | ❌ | ✅ one command |
| Auto-snapshot on change (`watch`) | ❌ | ✅ built-in |
| Content-addressed dedup | ✅ | ✅ |
| Restore a single file from history | ✅ | ✅ |
| Branching / merging / collaboration | ✅ | ❌ (out of scope) |

FoldChrono is **not** a git replacement. It's a safety net for the folders git never touches.

---

## Features

- 📸 **`snapshot`** — record the full state of any directory in seconds
- 🔍 **`diff`** — compare two snapshots, or a snapshot against the live working tree
- ♻️ **`restore`** — bring back files (or a glob-filtered subset) to any output directory
- 👀 **`watch`** — continuously monitor a folder and auto-snapshot when anything changes
- 🧹 **`gc`** — reclaim disk space by deleting blobs no longer referenced by any snapshot
- 🗜️ **Deduplication** — identical content stored once, across all snapshots
- 📦 **Zero dependencies** — pure Python standard library, installs anywhere
- 💾 **Local-first** — everything stays under `~/.foldchrono`; nothing ever leaves your machine

---

## Installation

Requires **Python 3.9+**.

```bash
# from source (this repo)
pip install .

# or, for development
pip install -e .
```

This installs the `foldchrono` command.

---

## Quick start

```bash
# 1. Snapshot a folder
cd my-project
foldchrono snapshot -m "before risky refactor"
# → Snapshot #1 created (42 files, 1.2 MiB)

# 2. Make some changes (edit, delete, add files)…

# 3. See what changed since the last snapshot
foldchrono status
# → Compared to snapshot #1: 1 added, 1 removed, 2 modified
#     + new_feature.py
#     - old_helper.py
#     ~ main.py

# 4. Take another snapshot
foldchrono snapshot -m "after refactor"

# 5. Diff two snapshots
foldchrono diff --from 1 --to 2

# 6. Accidentally deleted something? Restore from snapshot #1
foldchrono restore 1 --to ./recovery_dir
# → Restored 42 file(s) from snapshot #1
```

---

## Command reference

| Command | Description |
|---|---|
| `foldchrono snapshot [PATH] [-m MSG]` | Record current state. PATH defaults to cwd. |
| `foldchrono list [PATH]` | List all snapshots (optionally filtered by path). |
| `foldchrono show <ID>` | Show metadata + full file list of a snapshot. |
| `foldchrono diff [PATH] [--from ID] [--to ID]` | Diff. With no flags: latest snapshot vs working tree. `--from` only: that snapshot vs working tree. Both: snapshot vs snapshot. |
| `foldchrono status [PATH]` | Shortcut for `diff` against the latest snapshot. |
| `foldchrono log <FILE> [PATH]` | Show change history of a single file across all snapshots (added / modified / unchanged). |
| `foldchrono restore <ID> [--to DIR] [--file GLOB] [-v]` | Restore files. `--to` defaults to `./foldchrono_restore_<ID>_<timestamp>`. `--file` filters by glob. |
| `foldchrono watch [PATH] [-i SECONDS]` | Poll every N seconds (default 30) and auto-snapshot on change. |
| `foldchrono rm <ID>` | Delete a snapshot's metadata (run `gc` to free blobs). |
| `foldchrono gc` | Remove unreferenced blobs to reclaim disk space. |

Global flag: `--data-dir PATH` overrides the storage location (default `~/.foldchrono`).

---

## How it works

```
┌─────────────────────────────────────────────────┐
│  ~/.foldchrono/                                 │
│  ├── foldchrono.db        ← SQLite metadata     │
│  │   ├── snapshots        (id, path, time, …)   │
│  │   └── files            (snapshot_id, path,   │
│  │                         size, mtime, sha256) │
│  └── blobs/               ← content-addressed   │
│      ├── ab/              store (git-style      │
│      │   └── c123…        fan-out by hash)      │
│      └── …                                     │
└─────────────────────────────────────────────────┘
```

1. **Snapshot** walks the directory, hashes each file with SHA-256, and copies the body into `blobs/<hash[:2]>/<hash[2:]>`. If that hash already exists, the copy is skipped — **dedup is automatic**.
2. **Metadata** (which relative path had which hash at which snapshot) goes into SQLite.
3. **Diff** is just a hash-map comparison — instant, even for huge histories.
4. **Restore** looks up the hashes for a snapshot and copies the corresponding blobs back out.
5. **GC** walks the blob directory and deletes anything no longer referenced by `files`.

---

## Ignoring files

FoldChrono always skips common noise (`.git`, `node_modules`, `__pycache__`, `*.pyc`, etc.). Add a `.foldchronoignore` file in the snapshot root for custom patterns (gitignore-lite syntax — one pattern per line, `#` comments, `*` globs):

```
# .foldchronoignore
build/
dist/
*.log
secrets/
```

---

## Data & safety

- **Everything is local.** No network calls, no telemetry, no cloud.
- **Snapshots are additive.** Taking a new snapshot never modifies or deletes old ones.
- **Restore writes to a separate directory** by default — it never overwrites your original folder in place.
- **Blobs are content-addressed and immutable** once written.
- To fully wipe history: `foldchrono rm <ID>` for each snapshot, then `foldchrono gc`, or delete `~/.foldchrono` entirely.

---

## Development

```bash
# run the test suite (stdlib unittest, no extra deps)
python -m unittest discover -s tests -v

# install in editable mode
pip install -e .
```

Project layout:

```
foldchrono/
├── foldchrono/
│   ├── cli.py        # argparse entry point & subcommands
│   ├── core.py       # snapshot engine, hashing, ignore rules
│   ├── storage.py    # SQLite + content-addressed blob store
│   ├── diff.py       # diff computation
│   └── restore.py    # restore logic
├── tests/            # unittest suite (core, diff, restore, CLI e2e)
├── pyproject.toml
└── README.md
```

---

## Roadmap (ideas)

- [ ] FUSE / virtual mount: browse any snapshot as a read-only filesystem
- [ ] `foldchrono log <file>`: per-file history across snapshots
- [ ] Compressed blob storage (zstd)
- [ ] Encrypted blob option for sensitive folders
- [ ] Export a snapshot as a tar/zip archive

Contributions welcome — open an issue or PR.

---

## License

[MIT](LICENSE)
