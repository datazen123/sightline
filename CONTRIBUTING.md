# Contributing

> New to a term? Every acronym is spelled out the first time it appears, and all of them live in the [Glossary](GLOSSARY.md).

1. `uv sync`, then `uv run pytest -q && uv run ruff check .` must pass before and after your change.
2. **Code computes, AI (artificial intelligence) explains.** Any new number in a finding must come from code with a unit
   test. Never let model output flow into an amount, and never loosen a reconciliation check
   to make a file pass.
3. Every deterministic check gets tests for the positive case and at least one clean case.
4. New domains go in `corpora/<name>/` (see `docs/ARCHITECTURE.md#adding-a-corpus`) with
   synthetic data and a seeded-issues file. Report eval (evaluation against known answers) results as they are, misses included.
5. Synthetic data only. Do not commit real invoices, contracts, customer names, keys or
   `.env` files.
6. Small commits with clear messages; one concern per pull request.
