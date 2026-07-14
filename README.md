# OpenMetadata — Hive: nested `DECIMAL(p,s)` breaks column ingestion

A reproducible bug report, a self-contained local repro environment, and a patch for OpenMetadata's Hive connector.

## TL;DR

A Hive column whose type is `ARRAY<STRUCT<... DECIMAL(p,s) ...>>` or `MAP<..., DECIMAL(p,s)>` makes `get_columns()` throw:

```
ValueError: invalid literal for int() with base 10: '16,4'
```

The exception is swallowed in `sql_column_handler.py:297` and only surfaces as a `WARNING`, so the ingestion workflow reports **`Workflow Success %: 100.0, Errors: 0`** while the table lands in OpenMetadata **with zero columns**. The failure is silent — the pipeline status gives no hint that column metadata was lost.

A top-level `STRUCT<... DECIMAL(p,s) ...>` works, because `get_columns()` special-cases `struct` — but not `array` / `map`.

Reproduced on **openmetadata-ingestion 1.12.12**. The same code is present in `main` and in the `1.13` branch.

## What's here

| Path | |
|---|---|
| `docs/BUG_REPORT.md` | Full write-up: environment, DDL, repro matrix, full DEBUG stack trace, root-cause analysis |
| `patches/om-1.12.12-hive-nested-decimal.patch` | The fix, against tag `1.12.12-release` |
| `docs/HOW_TO_APPLY.md` | How to apply the patch (installed package / Docker image / source tree) |
| `repro/` | Self-contained local environment: Hive 4.0.1 + Metastore on PostgreSQL, DDL, ingestion config |

## The fix

`ingestion/src/metadata/ingestion/source/database/hive/utils.py` decides whether a type is complex by inspecting `attype`, a string that a greedy `re.sub(r"\(.*\)", "", col_type)` has already mangled. For `array<struct<fee_a:decimal(16,4),...>>` it becomes `"array<struct<fee_a:decimal,..."`, so the `attype.startswith("struct")` branch misses, while `charlen` has already picked up `16,4` from the *nested* decimal — and `int("16,4")` blows up.

The patch keys the decision off the **outer** type name (`col_type`), which is already computed a few lines above and already used for the `is_complex` flag, via the module's existing `complex_data_types` list (this also covers `uniontype`):

```diff
-            if attype == "decimal":
+            if any(col_type.startswith(prefix) for prefix in complex_data_types):
+                args = []
+            elif attype == "decimal":
                 prec, scale = charlen.split(",")
                 args = (int(prec), int(scale))
-            elif attype.startswith("struct"):
-                args = []
             else:
                 args = (int(charlen),)
```

Nested fields are not lost: they are parsed downstream by `ColumnTypeParser` from the raw `system_data_type` string.

The patch also sets `precision` / `scale` on **nested** decimals in `column_type_parser.py` — previously the precision silently ended up in `dataLength` and `precision`/`scale` stayed `None`. Top-level decimal columns were already correct.

## Reproducing locally

Requires Docker and Python 3.10–3.12.

```bash
cd repro
./setup.sh                      # Hive 4.0.1 + Metastore on PostgreSQL, then applies the DDL

python -m venv .venv && .venv/bin/pip install "openmetadata-ingestion[hive]==1.12.12" cachetools
.venv/bin/python repro_get_columns.py
```

Expected on unpatched 1.12.12:

```
plain_decimal          OK (3 columns)
struct_decimal         OK (2 columns)
array_struct_bigint    OK (2 columns)
array_struct_decimal   FAIL ValueError: invalid literal for int() with base 10: '16,4'
map_decimal            FAIL ValueError: invalid literal for int() with base 10: '10,2'
```

After applying the patch (see `docs/HOW_TO_APPLY.md`), all five tables return their columns.

To reproduce the *silent* part — the table landing with zero columns while the workflow reports success — point `repro/hive-ingestion.yaml` at an OpenMetadata server and run `metadata ingest -c hive-ingestion.yaml`.

## Status

Not yet filed upstream. The bug is live in `main` and `1.13`, so the patch has to be carried across upgrades until a fix lands.
