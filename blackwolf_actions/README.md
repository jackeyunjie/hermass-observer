# Blackwolf Actions

This folder standardizes Blackwolf downloads for local Python and Agently-compatible workflows.

## Token Setup

Do this once on the local machine:

```bash
python3 blackwolf_actions/configure_token.py --stdin
```

Paste the token, then press `Ctrl-D`.

The token is stored at:

```text
config/secrets/blackwolf_token.txt
```

The file is ignored by git and chmodded to `0600`. Token values must not be printed, committed, or copied into scripts.

Token lookup order:

1. `BLACKWOLF_TOKEN` environment variable
2. macOS Keychain if configured
3. `config/secrets/blackwolf_token.txt`
4. stdin only for scripts that explicitly allow it

## Daily Data Test

```bash
python3 blackwolf_actions/download_daily.py \
  --date 2026-05-21 \
  --base-date 2026-05-20 \
  --test
```

This writes a test zip under the research repo and a summary under:

```text
reports/blackwolf_actions/
```

## Recent Moneyflow

Use the latest all-three E/F pool as the code list:

```bash
python3 blackwolf_actions/download_moneyflow_recent.py \
  --end-date 2026-05-21 \
  --days 5
```

Smoke test with a small limit:

```bash
python3 blackwolf_actions/download_moneyflow_recent.py \
  --end-date 2026-05-21 \
  --days 2 \
  --limit 10
```

## Agently Mapping

Each script is an Action:

- `download_daily.py` = daily OHLCV Action
- `download_moneyflow_recent.py` = moneyflow evidence Action
- `import_moneyflow_duckdb.py` = long-lived moneyflow DuckDB import Action
- `build_moneyflow_evidence.py` = 5-day derived evidence Action sourced from DuckDB

Long-lived moneyflow DB:

```text
outputs/blackwolf_moneyflow/blackwolf_moneyflow.duckdb
```

Normal daily moneyflow update after the DB is bootstrapped:

```bash
python3 blackwolf_actions/download_moneyflow_recent.py --end-date YYYY-MM-DD --days 1
python3 blackwolf_actions/import_moneyflow_duckdb.py --date YYYY-MM-DD
python3 blackwolf_actions/build_moneyflow_evidence.py --date YYYY-MM-DD --days 5 --no-csv-fallback
```
- `token_provider.py` = credential provider shared by Actions

The DAG runner can call these Actions before P116 foundation/recommendation steps.
