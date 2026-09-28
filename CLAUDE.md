# Working on Vanguard-GTM

- Every behaviour, config, CLI, API or schema change also updates, in the same change:
  - `docs/DESIGN.md`, including its §17 change-log row
  - `docs/PROGRAMMERS_MANUAL.md`
  - `CHANGELOG.md`
  - `docs/TEST_CASES.md` for new tests

  `pytest` enforces this through `tests/test_docs_sync.py`.
- New end-to-end tests go in `tests/test_e2e.py`, with the docstring starting `E2E-NN:`.
- Keep the $0 default: nothing may call the Claude API unless `VANGUARD_MAX_COST_USD` is above 0.
  Integrations must be free to use, or gated the same way.
- Nothing sends email or publishes. Exports stay behind `approve`.
- `config/properties.yaml` positioning comes from the product repos under `vireoka-dev`. Mark
  anything else `needs_review`.
- Never copy secrets from the product repos into this project.
