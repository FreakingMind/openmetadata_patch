# Deploying the fix into an Airflow image

For deployments where `openmetadata-ingestion` is installed into a custom Airflow
image via `requirements.txt` (OpenMetadata pushes ingestion DAGs to *your* Airflow,
which runs the `metadata` code). Applies to any executor — the fix lands in the image,
so KubernetesExecutor worker pods pick it up automatically.

## Why a Python script instead of the `.patch`

`patches/om-1.12.12-hive-nested-decimal.patch` needs the `patch` binary and, on some
base images, root. `apply_hive_fix.py` needs neither: it locates the installed package
via `import metadata`, edits it in place, is idempotent, checks the version, and exits
non-zero if anything is off — so a broken build never ships silently.

It applies the same two fixes as the patch:
1. `hive/utils.py` — nested `DECIMAL(p,s)` inside `ARRAY`/`MAP` no longer crashes column
   reflection (issue #30061).
2. `column_type_parser.py` — nested decimals keep their `precision`/`scale`.

## Dockerfile

Copy `apply_hive_fix.py` into the build context, then add two lines **right after**
the step that installs `requirements.txt`:

```dockerfile
RUN pip install -r ./requirements.txt

# OpenMetadata #30061 — nested DECIMAL in ARRAY/MAP (Hive)
COPY apply_hive_fix.py /tmp/apply_hive_fix.py
RUN python /tmp/apply_hive_fix.py
```

No `USER root`, no `apt-get`, no `patch` needed — the package lives under
`~/.local/...` (installed as `USER airflow`) and the script writes there directly.

## Verifying

At build time the script prints `patched: utils.py` / `patched: column_type_parser.py`
and exits 0. To check a running pod:

```bash
python -c "import metadata,os,pathlib; \
p=pathlib.Path(os.path.dirname(metadata.__file__))/'ingestion/source/database/hive/utils.py'; \
print('PATCHED' if 'complex_data_types)' in p.read_text() else 'NOT PATCHED')"
```

After rebuilding and rolling out the image, re-run the Hive ingestion pipeline. The
DAG log must no longer contain `invalid literal for int() with base 10`, and the
affected table returns its columns (was 0) via
`GET /api/v1/tables/name/<fqn>?fields=columns`.

## Version

Built for `openmetadata-ingestion==1.12.12` (pip reports `1.12.12.0`). For any other
version the script aborts the build — rebuild the fix against that version.
