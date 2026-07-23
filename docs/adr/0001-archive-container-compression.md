# ADR 0001: Archive compression boundary

- Status: Accepted for Framework Alpha
- Date: 2026-07-23
- Scope: Newly implemented `.sandbox` archive only

## Context

The v0.2 layout names event and checkpoint members with `.zst` suffixes. A `.sandbox` file is already an application archive container. Requiring a second compression codec inside that container adds an install and recovery dependency without changing the event, checkpoint, hash, or branch-tree contracts exercised by the first vertical slice.

## Decision

Framework Alpha writes canonical JSON/JSONL members into a ZIP container using Deflate. The manifest hashes the uncompressed member bytes. Import validates paths, file count, expanded size boundary, schema, runtime version, and every member hash before restoring state.

The compression implementation remains owned by `ArchiveService`; domain and API code do not depend on ZIP or Deflate. A later benchmark may replace members with Zstandard without changing authoritative domain contracts.

## Consequences

- Archives are self-contained and inspectable with common tooling.
- The current member names are `.json` and `.jsonl`, not `.json.zst` and `.jsonl.zst`.
- Cross-version migration remains deferred, as required by v0.2.

