CREATE DATABASE IF NOT EXISTS test_nested_types;

-- FAILS: DECIMAL(p,s) nested inside ARRAY<STRUCT<...>>
DROP TABLE IF EXISTS test_nested_types.array_struct_decimal;
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
DROP TABLE IF EXISTS test_nested_types.map_decimal;
CREATE EXTERNAL TABLE test_nested_types.map_decimal(
    id STRING,
    fees MAP<STRING, DECIMAL(10,2)>
)
COMMENT 'Repro: decimal nested in map<>'
STORED AS PARQUET;

-- OK (control): top-level STRUCT is handled by the existing `attype.startswith("struct")` branch
DROP TABLE IF EXISTS test_nested_types.struct_decimal;
CREATE EXTERNAL TABLE test_nested_types.struct_decimal(
    id STRING,
    fees STRUCT<fee_a: DECIMAL(16,4), amount: BIGINT>
)
STORED AS PARQUET;

-- OK (control): complex type without a nested DECIMAL
DROP TABLE IF EXISTS test_nested_types.array_struct_bigint;
CREATE EXTERNAL TABLE test_nested_types.array_struct_bigint(
    id STRING,
    items ARRAY<STRUCT<amount: BIGINT, item_name: STRING>>
)
STORED AS PARQUET;

-- OK (control): top-level DECIMAL
DROP TABLE IF EXISTS test_nested_types.plain_decimal;
CREATE EXTERNAL TABLE test_nested_types.plain_decimal(
    id STRING,
    fee DECIMAL(16,4),
    name VARCHAR(255)
)
STORED AS PARQUET;
