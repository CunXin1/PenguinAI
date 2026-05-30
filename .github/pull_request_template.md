## What

<!-- One paragraph: what does this PR do? -->

## Why

<!-- Why is this change needed? Link to issue if applicable. -->

## Changes

- 
- 

## Test Plan

<!-- How did you verify this works? Check all that apply. -->
- [ ] Ran `make test` locally — all pass
- [ ] Ran `make lint` — no errors
- [ ] Tested in browser / API manually
- [ ] Verified signal output schema unchanged (or updated types.ts + schemas/signal.py together)
- [ ] No new secrets committed (checked with `git diff`)

## Signal Contract

<!-- If this PR touches signal generation or the signal schema: -->
- [ ] Not applicable
- [ ] `signal_cache` table schema unchanged
- [ ] `schemas/signal.py` + `frontend/src/lib/types.ts` updated together

## DB Migrations

- [ ] No schema changes
- [ ] Added Alembic migration in `db/migrations/`
