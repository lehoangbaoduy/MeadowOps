# MeadowOps Documentation

System documentation for Phase 4 / Unit 31 (PRD §1.6, §5.8).

- [schema-diagram.md](schema-diagram.md) — generated. One Mermaid ER diagram per schema plus cross-schema foreign keys.
- [data-dictionary.md](data-dictionary.md) — generated. Every table/column, keys, defaults, constraints.
- [data-flow.md](data-flow.md) — hand-authored. The lag, sandbox, and API boundaries the PRD treats as load-bearing.
- [testing-report.md](testing-report.md) — hand-authored. Regenerable suite counts, coverage gaps, edge-case catalog status.
- [walkthrough-script.md](walkthrough-script.md) — hand-authored. A live, no-improvisation demo script using QA/synthetic data.

`schema-diagram.md` and `data-dictionary.md` are generated from the live
SQLAlchemy metadata, not hand-written — regenerate after any migration:

```bash
cd backend && uv run --frozen python ../scripts/generate_docs.py
```
