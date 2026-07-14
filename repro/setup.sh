#!/usr/bin/env bash
# Brings up Hive 4.0.1 (HiveServer2 + standalone Metastore on PostgreSQL) and applies the repro DDL.
set -euo pipefail

cd "$(dirname "$0")"

PG_JDBC_VERSION=42.7.3
PG_JDBC_JAR="jars/postgresql-${PG_JDBC_VERSION}.jar"

if [ ! -f "$PG_JDBC_JAR" ]; then
    echo "==> Downloading PostgreSQL JDBC driver (needed by the Hive metastore)"
    mkdir -p jars
    curl -sSL -o "$PG_JDBC_JAR" \
        "https://repo1.maven.org/maven2/org/postgresql/postgresql/${PG_JDBC_VERSION}/postgresql-${PG_JDBC_VERSION}.jar"
fi

echo "==> Starting Hive"
docker compose -f docker-compose.hive.yml up -d

echo "==> Waiting for HiveServer2 to accept connections (this takes a minute)"
until docker exec hive-server2 beeline -u 'jdbc:hive2://localhost:10000/' -e 'SHOW DATABASES;' >/dev/null 2>&1; do
    sleep 5
done

echo "==> Applying DDL"
docker cp ddl/repro_ddl.sql hive-server2:/tmp/repro_ddl.sql
docker exec hive-server2 beeline -u 'jdbc:hive2://localhost:10000/' -f /tmp/repro_ddl.sql

echo
echo "==> Ready. The metastore now reports this type for array_struct_decimal.items:"
docker exec hive-server2 beeline -u 'jdbc:hive2://localhost:10000/test_nested_types' \
    -e 'DESCRIBE array_struct_decimal;' 2>/dev/null | grep items || true

echo
echo "Next: python repro_get_columns.py"
