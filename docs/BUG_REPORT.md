# Hive connector: tables with `DECIMAL(p,s)` nested inside `ARRAY<STRUCT<...>>` / `MAP<...>` are ingested with **zero columns** (workflow still reports 100% success)

## Summary

When a Hive column is a complex type (`ARRAY`, `MAP`) that contains a `DECIMAL(p,s)` field, `get_columns()` raises `ValueError: invalid literal for int() with base 10: '16,4'`.

The exception is swallowed by `sql_column_handler.py:297` (logged as a `WARNING`, full traceback only at `DEBUG`), so:

* the ingestion workflow finishes with **`Workflow Success %: 100.0`, `Errors: 0`, `Warnings: 0`**,
* but the table is created in OpenMetadata **with an empty column list**.

This makes the failure effectively silent — nothing in the pipeline status indicates that column metadata was lost.

A top-level `STRUCT<... DECIMAL(p,s) ...>` works, because `get_columns()` has an explicit branch for it. `ARRAY` / `MAP` have no such branch.

## Environment

| | |
|---|---|
| openmetadata-ingestion | **1.12.12** (also reproduced by code inspection on `main` and `1.13`, see "Affected versions") |
| OpenMetadata server | 1.12.5 (local docker) |
| Hive | 4.0.1 (HiveServer2 + standalone Metastore backed by PostgreSQL) |
| Connector | Hive, connecting to HiveServer2 (`localhost:10000`) |
| PyHive / SQLAlchemy / Python | 0.7.0 / 1.4.54 / 3.12 |

## Steps to reproduce

### 1. DDL

```sql
CREATE DATABASE IF NOT EXISTS test_nested_types;

-- FAILS: DECIMAL(p,s) nested inside ARRAY<STRUCT<...>>
CREATE EXTERNAL TABLE test_nested_types.array_struct_decimal(
    id STRING COMMENT 'Identifier',
    items ARRAY<STRUCT<
        fee_a: DECIMAL(16,4),
        fee_b: DECIMAL(16,4),
        amount: BIGINT,
        item_name: STRING
    >> COMMENT 'Nested items'
)
COMMENT 'Repro: decimal nested in array<struct<>>'
PARTITIONED BY (dt STRING)
STORED AS PARQUET;

-- FAILS: DECIMAL(p,s) nested inside MAP<...>
CREATE EXTERNAL TABLE test_nested_types.map_decimal(
    id STRING,
    fees MAP<STRING, DECIMAL(10,2)>
)
STORED AS PARQUET;

-- OK (control): top-level STRUCT with a DECIMAL
CREATE EXTERNAL TABLE test_nested_types.struct_decimal(
    id STRING,
    fees STRUCT<fee_a: DECIMAL(16,4), amount: BIGINT>
)
STORED AS PARQUET;

-- OK (control): complex type without a nested DECIMAL
CREATE EXTERNAL TABLE test_nested_types.array_struct_bigint(
    id STRING,
    items ARRAY<STRUCT<amount: BIGINT, item_name: STRING>>
)
STORED AS PARQUET;

-- OK (control): top-level DECIMAL
CREATE EXTERNAL TABLE test_nested_types.plain_decimal(
    id STRING,
    fee DECIMAL(16,4),
    name VARCHAR(255)
)
STORED AS PARQUET;
```

The type string returned by the metastore for the failing column is:

```
array<struct<fee_a:decimal(16,4),fee_b:decimal(16,4),amount:bigint,item_name:string>>
```

### 2. Ingestion config

```yaml
source:
  type: hive
  serviceName: hive_test
  serviceConnection:
    config:
      type: Hive
      username: hive
      hostPort: localhost:10000
      auth: NONE
  sourceConfig:
    config:
      type: DatabaseMetadata
      includeTables: true
      schemaFilterPattern:
        includes:
          - test_nested_types
sink:
  type: metadata-rest
  config: {}
workflowConfig:
  loggerLevel: DEBUG
  openMetadataServerConfig:
    hostPort: http://localhost:8585/api
    authProvider: openmetadata
    securityConfig:
      jwtToken: "<token>"
```

```bash
metadata ingest -c hive-debug.yaml
```

## Actual result

Ingested column counts (via `GET /api/v1/tables/name/{fqn}?fields=columns`):

| Table | Column type | Columns in OpenMetadata |
|---|---|---|
| `array_struct_decimal` | `array<struct<...decimal(16,4)...>>` | **0** ❌ |
| `map_decimal` | `map<string,decimal(10,2)>` | **0** ❌ |
| `struct_decimal` | `struct<...decimal(16,4)...>` | 2 ✅ |
| `array_struct_bigint` | `array<struct<...bigint...>>` | 2 ✅ |
| `plain_decimal` | `decimal(16,4)` | 3 ✅ |

Workflow summary for the very same run:

```
Processed records: 10
Updated records: 0
Warnings: 0
Errors: 0
Success %: 100.0
Workflow Success %: 100.0
```

## Full stack trace (loggerLevel: DEBUG)

```
[2026-07-14 21:13:13] DEBUG    {metadata.Ingestion:sql_column_handler:296} - Traceback (most recent call last):
  File ".../site-packages/metadata/ingestion/source/database/sql_column_handler.py", line 292, in get_columns_and_constraints
    columns = self._get_columns_internal(
              ^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File ".../site-packages/metadata/ingestion/source/database/sql_column_handler.py", line 238, in _get_columns_internal
    return inspector.get_columns(
           ^^^^^^^^^^^^^^^^^^^^^^
  File ".../site-packages/sqlalchemy/engine/reflection.py", line 497, in get_columns
    col_defs = self.dialect.get_columns(
               ^^^^^^^^^^^^^^^^^^^^^^^^^
  File ".../site-packages/metadata/ingestion/source/database/hive/utils.py", line 73, in get_columns
    args = (int(charlen),)
            ^^^^^^^^^^^^
ValueError: invalid literal for int() with base 10: '16,4'

[2026-07-14 21:13:13] WARNING  {metadata.Ingestion:sql_column_handler:297} - Unexpected exception getting columns for table [array_struct_decimal] (schema: 'test_nested_types', db: 'default'): invalid literal for int() with base 10: '16,4'
```

The same trace is raised for `map_decimal` with `'10,2'`.

## Root cause

`ingestion/src/metadata/ingestion/source/database/hive/utils.py`, `get_columns()` (lines ~55-75):

```python
col_raw_type = col_type
attype = re.sub(r"\(.*\)", "", col_type)          # greedy — eats everything between the FIRST "(" and the LAST ")"
col_type = re.search(r"^\w+", col_type).group(0)  # outer type name -> "array"
...
charlen = re.search(r"\(([\d,]+)\)", col_raw_type.lower())   # matches the NESTED decimal's params -> "16,4"
if charlen:
    charlen = charlen.group(1)
    if attype == "decimal":
        prec, scale = charlen.split(",")
        args = (int(prec), int(scale))
    elif attype.startswith("struct"):             # only STRUCT is special-cased
        args = []
    else:
        args = (int(charlen),)                    # int("16,4") -> ValueError
    coltype = coltype(*args)
```

Two problems combine:

1. `charlen` is searched over the **whole** raw type string, so for a complex type it matches the parameters of a *nested* type (`decimal(16,4)` → `"16,4"`).
2. Whether the type is complex is decided from `attype`, which the greedy `re.sub` has already mangled. For `array<struct<fee_a:decimal(16,4),...>>` the result is `"array<struct<fee_a:decimal,..."`, so `attype.startswith("struct")` is `False` and execution falls through to `int(charlen)`.

Only the top-level `STRUCT` case is covered by the existing branch; `ARRAY`, `MAP` (and `UNIONTYPE`) are not.

## Related (separate, minor) issue

`ColumnTypeParser._parse_primitive_datatype_string()` (`column_type_parser.py:439-450`) does not set `precision` / `scale` for **nested** decimals — it puts the precision into `dataLength` instead:

```
items.fee_a  ->  dataType=DECIMAL, dataTypeDisplay='decimal(16,4)', dataLength=16, precision=None, scale=None
```

Top-level decimal columns are fine (`precision=16, scale=4`) because `check_col_precision()` handles them in `sql_column_handler`. Happy to file this separately if useful.

## Affected versions

Reproduced on **1.12.12**. The same code is present in `main` and in the `1.13` release branch:
`ingestion/src/metadata/ingestion/source/database/hive/utils.py` — the `attype.startswith("struct")` branch is unchanged there, so the bug should reproduce on those as well.
