# InferBench Agent Map

This file is a map, not a handbook. Keep it short. Follow links for details and update the repository record when behavior or decisions change.

## Start here

- Product and usage: [README.md](README.md)
- Architecture and dependency flow: [ARCHITECTURE.md](ARCHITECTURE.md)
- Development and release gates: [CONTRIBUTING.md](CONTRIBUTING.md)
- Knowledge index: [docs/README.md](docs/README.md)
- Product contract: [docs/product-specs/benchmark-contract.md](docs/product-specs/benchmark-contract.md)
- Engineering beliefs: [docs/design-docs/core-beliefs.md](docs/design-docs/core-beliefs.md)
- Quality status and debt: [docs/QUALITY.md](docs/QUALITY.md)
- Execution plans: [docs/exec-plans/README.md](docs/exec-plans/README.md)

## Repository shape

- `inferbench/models.py`: validated boundary models and persisted configuration.
- `inferbench/adapter.py`: OpenAI-compatible request and SSE parsing.
- `inferbench/database.py`: SQLite/WAL persistence.
- `inferbench/metrics.py`: summaries, aggregation, comparison and scoring.
- `inferbench/runner.py`: queueing, concurrency, cancellation and run lifecycle.
- `inferbench/main.py`: FastAPI control plane, discovery, mock target and exports.
- `inferbench/static/`: dependency-free dashboard.
- `tests/`: unit, API and browser smoke coverage.
- `scripts/`: executable repository checks and release helpers.

Python dependencies flow forward only:

```text
models -> adapter/database/metrics -> runner -> main
```

Cross-layer shortcuts require an architecture decision and a checker update in the same PR.

## Mandatory workflow

1. Inspect the worktree.
2. Run `git fetch origin --prune --tags`.
3. Rebase `lixie` on `origin/master` before editing.
4. Preserve unrelated user changes; never stage them.
5. For complex work, create an execution plan from the repository template.
6. Implement the smallest coherent change and update its source-of-truth docs.
7. Run `./scripts/verify.sh` and review the complete diff.
8. Push `lixie` and create or update the `lixie -> master` PR.
9. Stop for administrator review and merge confirmation.
10. After merge, separately ask the administrator to confirm the exact Tag.

Never merge a PR or create, move or delete a release Tag without the relevant explicit administrator confirmation.

## Validation rules

- Use boundary models instead of probing unknown payload shapes.
- Keep API keys in memory; never persist or log them.
- Preserve raw request samples so summaries remain recomputable.
- Cancellation must stop queued work and interrupt active streams.
- Benchmark repetitions are independent runs; comparisons aggregate them explicitly.
- UI changes need browser evidence when behavior or layout changes.
- Run repository checks before requesting review.
- Docker images are built and pushed only by GitHub Actions, never locally.

## Documentation rule

If a review comment, production failure or repeated correction reveals a reusable rule, encode it in one of these places in the same or a follow-up PR:

- a test or mechanical checker;
- an architecture/product document;
- the development workflow;
- the quality and technical-debt record.

Prefer enforceable invariants over longer instructions.
