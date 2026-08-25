# Roadmap

## 0.1: trustworthy local preview

- Add a bundled synthetic demo directory and one-command read-only preview.
- Separate measured tokenizer counts from price estimates in the UI and exports.
- Publish a versioned configuration schema and migration notes.
- Keep clean-clone tests and Docker builds green on every pull request.

## 0.2: reversible optimization

- Add an explicit dry-run/apply/restore lifecycle with conflict detection.
- Export machine-readable before/after reports without prompt contents by default.
- Benchmark simplification quality on a public synthetic corpus.

## 1.0 criteria

- Five independent users complete preview, apply, and restore without data loss.
- Every write path is atomic, locked, backed up, and regression-tested.
- Token savings are reproducible with a named tokenizer; monetary values are clearly
  labeled estimates.
- Provider-free local operation remains the default and no prompt data leaves the machine
  without explicit configuration.
