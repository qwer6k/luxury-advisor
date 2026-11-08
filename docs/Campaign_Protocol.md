# Campaign reproduction

The paid submission campaign has a persistent 144-request ceiling, including failures, format repairs and content rewrites. Phase limits: preflight 24, formal 100, supplemental 18, clean 2. Each invocation has at most two actual requests. SDK retries are disabled. Do not launch a separate fresh ledger to bypass this ceiling.

Freeze a new version without calls:
`uv run --env-file .env luxury-advisor --cases-file data/formal_cases.json --freeze NEW --manifest outputs/campaign/NEW.json`

Generate with the frozen version and persistent ledger:
`uv run --env-file .env luxury-advisor --cases-file data/formal_cases.json --live --manifest outputs/campaign/NEW.json --ledger outputs/campaign/budget.sqlite3 --phase formal --max-calls 144`

Use `--resume` to skip already attempted cases. Inputs, source, model configuration and dependencies must match the frozen manifest. Failed/interrupted attempts remain recorded and are not silently retried. The submission ledger includes prior formal runs; new campaigns require a separately authorized budget and must be reported separately. No additional campaign requests are needed to browse saved results.

All API-generated strings are untrusted drafts. Rules are limited checks, not proof of truth. Advisors verify catalog facts, service authority, latest requests and contact boundaries before use. The current UI blocks copying when blocking findings remain.
