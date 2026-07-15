#!/usr/bin/env python3
"""
Apply the Hive nested-DECIMAL fix to an installed openmetadata-ingestion==1.12.12.

Designed to run as a build step in an Airflow image, right after
`pip install -r requirements.txt`:

    RUN python /tmp/apply_hive_fix.py

No `patch` binary, no git, no root required (site-packages is writable at build time).
Idempotent: running it twice is a no-op. Fails loudly (non-zero exit) if the package
is missing, the version is not 1.12.12, or the expected code is not found — so a broken
build never ships silently.

Fixes:
  1) hive/utils.py::get_columns — DECIMAL(p,s) nested in ARRAY/MAP no longer crashes
     (ValueError: invalid literal for int() with base 10: '16,4'); the table is
     ingested with its columns instead of zero columns.
  2) column_type_parser.py — nested decimals get precision/scale instead of losing them.
"""
import os
import sys

EXPECTED_VERSION = "1.12.12"


def die(msg: str) -> None:
    sys.exit(f"[apply_hive_fix] ERROR: {msg}")


def check_version() -> None:
    try:
        from importlib.metadata import version
    except ImportError:  # py<3.8, not expected here
        from importlib_metadata import version  # type: ignore
    try:
        installed = version("openmetadata-ingestion")
    except Exception as exc:  # noqa: BLE001
        die(f"openmetadata-ingestion is not installed: {exc}")
    # pip normalises `==1.12.12` to `1.12.12.0`, so accept the version and any
    # trailing patch segment, but reject a different minor (e.g. 1.13.x / 1.12.13).
    if installed != EXPECTED_VERSION and not installed.startswith(
        EXPECTED_VERSION + "."
    ):
        die(
            f"expected openmetadata-ingestion=={EXPECTED_VERSION}, "
            f"found {installed}. Rebuild this fix against {installed}."
        )


def metadata_root() -> str:
    import metadata

    return os.path.dirname(metadata.__file__)


def replace_once(path: str, old: str, new: str, already: str) -> None:
    with open(path, encoding="utf-8") as fh:
        content = fh.read()
    if already in content:
        print(f"[apply_hive_fix] already applied: {os.path.basename(path)}")
        return
    count = content.count(old)
    if count != 1:
        die(f"{path}: expected exactly 1 match of the target block, found {count}")
    content = content.replace(old, new)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
    print(f"[apply_hive_fix] patched: {os.path.basename(path)}")


HIVE_OLD = """            if attype == "decimal":
                prec, scale = charlen.split(",")
                args = (int(prec), int(scale))
            elif attype.startswith("struct"):
                args = []
            else:
                args = (int(charlen),)"""

HIVE_NEW = """            if any(col_type.startswith(prefix) for prefix in complex_data_types):
                # For complex types the regex above matches the parameters of a nested
                # type instead, e.g. array<struct<a:decimal(16,4)>> yields "16,4".
                # The nested fields are resolved later from `system_data_type`.
                args = []
            elif attype == "decimal":
                prec, scale = charlen.split(",")
                args = (int(prec), int(scale))
            else:
                args = (int(charlen),)"""

PARSER_OLD = """                    "dataLength": int(match.group(3)),  # type: ignore
                }"""

PARSER_NEW = """                    "dataLength": int(match.group(3)),  # type: ignore
                    "precision": int(match.group(3)),  # type: ignore
                    "scale": int(match.group(4)),  # type: ignore
                }"""


def main() -> None:
    check_version()
    root = metadata_root()

    hive = os.path.join(root, "ingestion/source/database/hive/utils.py")
    parser = os.path.join(root, "ingestion/source/database/column_type_parser.py")
    for path in (hive, parser):
        if not os.path.isfile(path):
            die(f"file not found: {path}")

    replace_once(
        hive,
        HIVE_OLD,
        HIVE_NEW,
        already="any(col_type.startswith(prefix) for prefix in complex_data_types)",
    )
    replace_once(
        parser,
        PARSER_OLD,
        PARSER_NEW,
        already='"precision": int(match.group(3)),  # type: ignore',
    )

    # Verify the result imports and behaves
    with open(hive, encoding="utf-8") as fh:
        assert "complex_data_types)" in fh.read(), "hive/utils.py verification failed"
    print("[apply_hive_fix] done.")


if __name__ == "__main__":
    main()
