.PHONY: test test-reset db-up db-down eval

# Run the test suite against the local Supabase Postgres (starts it if needed).
# Pass extra pytest args via ARGS, e.g. `make test ARGS="tests/test_comments.py -q"`.
test: db-up
	uv run pytest $(ARGS)

# Rebuild the local DB schema from migrations, then run the suite.
# Use this after changing anything under supabase/migrations.
test-reset: db-up
	supabase db reset --local
	uv run pytest $(ARGS)

# Start the local Supabase stack only if it isn't already running.
db-up:
	@supabase status >/dev/null 2>&1 || supabase start

# Stop the local Supabase stack.
db-down:
	supabase stop

# Offline recommendation eval against the local Supabase Postgres.
# Replaces only movies 900001-900240 and @eval.local users. Dataset notes
# are in scripts/eval_recs.py.
eval: db-up
	uv run python scripts/eval_recs.py
