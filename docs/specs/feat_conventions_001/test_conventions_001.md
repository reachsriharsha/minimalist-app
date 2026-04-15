# Test Spec: Project Conventions, Spec Scaffolding, License, and README

This feature produces documentation only — no runtime code, no HTTP endpoints, no build pipeline. Tests are therefore **file-presence and content assertions** that a reviewer (or a simple shell/grep check) can verify on the merged branch. No test framework is introduced; `feat_testing_001` owns that.

All tests are run from the repository root on the `build/feat_conventions_001` branch after Vulcan's changes are applied.

## Happy Path

| # | Test Case | Input | Expected Output |
|---|---|---|---|
| 1 | `conventions.md` exists at repo root | `test -f conventions.md` | Exit code 0 |
| 2 | `LICENSE` exists at repo root | `test -f LICENSE` | Exit code 0 |
| 3 | `README.md` exists and is non-trivial | `wc -l < README.md` | Result > 10 (not the old one-liner) |
| 4 | `docs/specs/README.md` exists | `test -f docs/specs/README.md` | Exit code 0 |
| 5 | Feature spec file present | `test -f docs/specs/feat_conventions_001/feat_conventions_001.md` | Exit code 0 |
| 6 | Design spec file present | `test -f docs/specs/feat_conventions_001/design_conventions_001.md` | Exit code 0 |
| 7 | Test spec file present | `test -f docs/specs/feat_conventions_001/test_conventions_001.md` | Exit code 0 |
| 8 | `conventions.md` documents feature ID format | grep `feat_<domain>_<NNN>` in `conventions.md` | Match found |
| 9 | `conventions.md` documents branch naming | grep `spec/<feat_id>` and `build/<feat_id>` in `conventions.md` | Both matches found |
| 10 | `conventions.md` documents commit prefix | grep `autodev(<feat_id>)` in `conventions.md` | Match found |
| 11 | `conventions.md` lists all five approved feature IDs | grep each of `feat_conventions_001`, `feat_backend_001`, `feat_frontend_001`, `feat_infra_001`, `feat_testing_001` in `conventions.md` | All five matches found |
| 12 | `conventions.md` documents status vocabulary | grep each of `Planned`, `In Spec`, `Ready`, `In Build`, `Merged` in `conventions.md` | All five matches found |
| 13 | `conventions.md` names the locked tech stack | grep each of `FastAPI`, `Postgres`, `Redis`, `Vite`, `React`, `TypeScript`, `uv`, `bun`, `docker-compose` in `conventions.md` | All nine matches found |
| 14 | `LICENSE` is MIT | grep `MIT License` in `LICENSE` | Match found |
| 15 | `LICENSE` has correct copyright line | grep `Copyright (c) 2026 Sri Harsha` in `LICENSE` | Match found |
| 16 | `LICENSE` contains the standard warranty clause | grep `THE SOFTWARE IS PROVIDED "AS IS"` in `LICENSE` | Match found |
| 17 | `README.md` points to `conventions.md` | grep `conventions.md` in `README.md` | Match found |
| 18 | `README.md` points to `LICENSE` | grep `LICENSE` in `README.md` | Match found |
| 19 | `README.md` lists core stack keywords | grep each of `FastAPI`, `React`, `Postgres`, `Redis` in `README.md` | All four matches found |
| 20 | `docs/specs/README.md` explains the three-file spec convention | grep each of `feat_`, `design_`, `test_` in `docs/specs/README.md` | All three matches found |

## Error Cases

| # | Test Case | Input | Expected Behavior |
|---|---|---|---|
| 1 | No empty placeholder folders committed | `find . -type d -empty -not -path './.git/*'` | No results (design spec forbids empty folders) |
| 2 | Old one-line README stub replaced | grep-count of `^# minimalist-app$` as the only content of `README.md` | README contains more than just that line |
| 3 | Conventions file not accidentally placed under `docs/` | `test -f docs/conventions.md` | Exit code 1 (file must be at repo root, not under `docs/`) |
| 4 | License file has no trailing `TODO` or placeholder | grep -i `TODO\|FIXME\|xxx` in `LICENSE` | No matches |
| 5 | README does not claim features that don't exist yet as "working" | grep-style review: mentions of `backend/`, `frontend/`, `make up`, `bun run dev` must be qualified as "added by feat_xxx" or "coming soon" | Qualifiers present near every such mention |

## Boundary Conditions

| # | Test Case | Condition | Expected Behavior |
|---|---|---|---|
| 1 | Vulcan did not re-author the three spec files | `git diff main...build/feat_conventions_001 -- docs/specs/feat_conventions_001/` | Zero changes for the three spec files (they were merged in via the spec PR already) |
| 2 | `conventions.md` is at repository root, not nested | `find . -name conventions.md -not -path './.git/*'` | Exactly one result: `./conventions.md` |
| 3 | Linting/CI config not introduced | `ls .github/workflows/ 2>/dev/null \|\| true` and `ls .pre-commit-config.yaml 2>/dev/null \|\| true` | No such files (linting is a deferred feature) |
| 4 | No runtime code introduced | `find . -type f \( -name '*.py' -o -name '*.ts' -o -name '*.tsx' -o -name '*.js' \) -not -path './.git/*'` | No results |
| 5 | Repo still has no `backend/`, `frontend/`, `infra/`, `tests/`, `deployment/` folders | `test -d backend \|\| test -d frontend \|\| test -d infra \|\| test -d tests \|\| test -d deployment` | All five return non-zero (folders do not yet exist) |

## Security Considerations

- **License correctness:** The MIT text must match the canonical text exactly. A malformed license (missing the "AS IS" warranty clause, wrong SPDX name, or altered terms) could create ambiguity for downstream users. Test cases 14-16 enforce the canonical markers.
- **No secrets or credentials in docs:** `README.md` and `conventions.md` must not contain tokens, passwords, API keys, or private email addresses. Reviewer checks by visual inspection; automatable via a simple grep for patterns like `AWS_`, `BEGIN RSA`, `ghp_`, `sk_live_` (no matches expected).
- **Copyright holder accuracy:** The LICENSE names `Sri Harsha` as the copyright holder per user instruction. Any change to the holder name in a future PR should go through explicit human review.
- **No executable scripts introduced:** This feature must not add any shell scripts, `Makefile` targets, or CI workflows. Boundary test 3 enforces this.
