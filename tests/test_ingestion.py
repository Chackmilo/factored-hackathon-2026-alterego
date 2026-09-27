"""
Tests for which S3 partitions the ingestion pipeline reads, against a local copy of the partition layout.
"""
import duckdb
import pytest

from src.data.ingestion import transactions_glob

PARTITIONS = [
    "year=2023/month=07/day=01",
    "year=2025/month=01/day=15",
    "year=2026/month=05/day=02",
    "year=2026/month=06/day=10",
]


@pytest.fixture
def partition_root(tmp_path):
    """Team-generated fixture: one empty CSV per daily partition, laid out like s3://<bucket>/data."""
    for partition in PARTITIONS:
        folder = tmp_path / "transactions" / partition
        folder.mkdir(parents=True)
        (folder / "part.csv").write_text("transaction_id\n")
    return tmp_path.as_posix()


def _matched_partitions(pattern: str) -> set:
    files = duckdb.sql(f"SELECT file FROM glob('{pattern}')").fetchall()
    return {"/".join(f.replace("\\", "/").split("/")[-4:-1]) for (f,) in files}


def test_full_load_reads_every_year(partition_root):
    """ML trains on 2023 to 2026, so sample_only=False must read every year's partitions."""
    assert _matched_partitions(transactions_glob(partition_root, sample_only=False)) == set(PARTITIONS)


def test_sample_reads_only_june_2026(partition_root):
    assert _matched_partitions(transactions_glob(partition_root, sample_only=True)) == {"year=2026/month=06/day=10"}
