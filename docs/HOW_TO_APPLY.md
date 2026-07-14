# How to apply the patch

`patches/om-1.12.12-hive-nested-decimal.patch` — 2 files, +8/−3 lines, against tag `1.12.12-release`
(verified byte-identical to the code shipped in `openmetadata-ingestion==1.12.12.0`).

The patch touches Python ingestion code only. **No OpenMetadata server or database restart is needed** — restart the ingestion worker (Airflow) and re-run the pipeline. Tables that were previously ingested with zero columns are backfilled on the next run.

## A. Into an installed package (venv or ingestion image) — quickest workaround

Paths inside the patch are repo-relative (`ingestion/src/metadata/...`), while `site-packages` contains `metadata/...` directly — so strip 3 leading components (`a/`, `ingestion/`, `src/`) with `-p3`:

```bash
SP=$(python -c "import metadata, os; print(os.path.dirname(os.path.dirname(metadata.__file__)))")
patch -p3 -d "$SP" < patches/om-1.12.12-hive-nested-decimal.patch
```

Verify it landed:

```bash
grep -A2 "complex_data_types)" "$SP/metadata/ingestion/source/database/hive/utils.py"
```

## B. Custom ingestion image

```dockerfile
FROM openmetadata/ingestion:1.12.12
USER root
COPY om-1.12.12-hive-nested-decimal.patch /tmp/
RUN SP=$(python -c "import metadata, os; print(os.path.dirname(os.path.dirname(metadata.__file__)))") \
    && patch -p3 -d "$SP" < /tmp/om-1.12.12-hive-nested-decimal.patch \
    && rm /tmp/om-1.12.12-hive-nested-decimal.patch
USER airflow
```

## C. Onto an OpenMetadata source tree

```bash
git checkout 1.12.12-release
git apply patches/om-1.12.12-hive-nested-decimal.patch
```

## Rollback

```bash
patch -R -p3 -d "$SP" < patches/om-1.12.12-hive-nested-decimal.patch
```

## Verifying the fix

Re-run ingestion. The log must no longer contain:

```
Unexpected exception getting columns for table [...]: invalid literal for int() with base 10: '16,4'
```

Then check the ingested table through the API:

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "$OM_HOST/api/v1/tables/name/<service>.<db>.<schema>.array_struct_decimal?fields=columns" \
  | jq '{columns: (.columns|length),
         children: (.columns[] | select(.name=="items") | .children | length),
         nested_decimal: (.columns[] | select(.name=="items") | .children[0] | {dataType, precision, scale})}'
```

Expected: the column list is non-empty, `items` carries its nested children, and nested decimals report `precision` / `scale` instead of `null`.

## Notes

- `column_type_parser.py` is shared by **all** connectors, not just Hive. The change there is additive (it adds `precision` / `scale`, removes nothing), but it does affect any source with nested decimals.
- No unit tests are included with the patch. The existing Hive unit tests (`ingestion/tests/unit/topology/database/test_hive.py`, 36 tests) pass with it applied.
