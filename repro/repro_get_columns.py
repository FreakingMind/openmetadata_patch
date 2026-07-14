"""
Minimal reproduction of the OpenMetadata Hive bug:
DECIMAL(p,s) nested inside ARRAY<STRUCT<...>> / MAP<...> breaks column reflection.

Importing the Hive source module patches HiveDialect.get_columns with OpenMetadata's
implementation (ingestion/src/metadata/ingestion/source/database/hive/utils.py), so this
goes through exactly the same code path as a real ingestion run.

    pip install "openmetadata-ingestion[hive]==1.12.12" cachetools
    python repro_get_columns.py
"""
from sqlalchemy import create_engine, inspect

import metadata.ingestion.source.database.hive.metadata  # noqa: F401  (patches HiveDialect.get_columns)
from metadata.ingestion.source.database.column_type_parser import ColumnTypeParser

SCHEMA = "test_nested_types"
TABLES = [
    "plain_decimal",
    "struct_decimal",
    "array_struct_bigint",
    "array_struct_decimal",
    "map_decimal",
]

engine = create_engine(f"hive://localhost:10000/{SCHEMA}")
inspector = inspect(engine)

for table in TABLES:
    try:
        columns = inspector.get_columns(table, schema=SCHEMA)
        print(f"{table:<24} OK ({len(columns)} columns)")
    except Exception as exc:  # noqa: BLE001
        print(f"{table:<24} FAIL {type(exc).__name__}: {exc}")

print("\n=== How ColumnTypeParser resolves the nested type ===")
nested_type = (
    "array<struct<fee_a:decimal(16,4),fee_b:decimal(16,4),"
    "amount:bigint,item_name:string>>"
)
parsed = ColumnTypeParser._parse_datatype_string(nested_type)
print("dataType:", parsed["dataType"], "arrayDataType:", parsed.get("arrayDataType"))
for child in parsed.get("children", []):
    print(
        f"  - {child['name']:<12} {child['dataType']:<8} "
        f"display={child.get('dataTypeDisplay')!r:<16} "
        f"precision={child.get('precision')} scale={child.get('scale')}"
    )
