"""
S3 Schema and Partition Inspector for OmniGuard AI / LATAM Bank Dataset.
Allows inspecting table schemas, column data types, and sample rows directly from S3 partitions.
"""
import argparse
import os
import duckdb
from dotenv import load_dotenv

load_dotenv()

TABLE_PATHS = {
    "daily_exchange_rates": "data/daily_exchange_rates.csv",
    "customers": "data/customers.csv",
    "products": "data/products.csv",
    "branches": "data/branches.csv",
    "transactions": "data/transactions/year=2026/month=06/day=01/transactions_20260601.csv",
    "complaints": "data/complaints/year=2026/month=06/day=01/complaints_20260601.csv",
    "call_center_interactions": "data/call_center_interactions/year=2025/month=03/*/*.csv",
    "call_transcripts": "data/call_transcripts/year=2025/month=03/*/*.csv",
    "satisfaction_surveys": "data/satisfaction_surveys/year=2025/month=03/*/*.csv",
}

def inspect_schemas(target_table: str = "all", limit: int = 3):
    aws_access_key_id = os.getenv("AWS_ACCESS_KEY_ID")
    aws_secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY")
    region = os.getenv("AWS_DEFAULT_REGION", "us-east-2")
    bucket = os.getenv("S3_BUCKET_NAME")

    if not bucket or not aws_access_key_id or not aws_secret_access_key:
        print("[ERROR] AWS credentials or S3_BUCKET_NAME missing in environment (.env).")
        return

    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs;")
    con.execute(f"SET s3_region='{region}';")
    con.execute(f"SET s3_access_key_id='{aws_access_key_id}';")
    con.execute(f"SET s3_secret_access_key='{aws_secret_access_key}';")

    selected_tables = (
        TABLE_PATHS
        if target_table == "all"
        else {target_table: TABLE_PATHS[target_table]}
        if target_table in TABLE_PATHS
        else None
    )

    if not selected_tables:
        print(f"[ERROR] Unknown table '{target_table}'. Available: {list(TABLE_PATHS.keys())}")
        return

    for name, rel_path in selected_tables.items():
        s3_url = f"s3://{bucket}/{rel_path}"
        print(f"\n{'='*20} {name} ({s3_url}) {'='*20}")
        try:
            df = con.execute(f"SELECT * FROM read_csv_auto('{s3_url}') LIMIT {limit};").df()
            print("Columns count:", len(df.columns))
            print("Columns:", list(df.columns))
            print("\nSample records:")
            for i, record in enumerate(df.to_dict(orient="records")):
                print(f"  [{i+1}] {record}")
        except Exception as e:
            print(f"  [ERROR] Failed to query {s3_url}: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Inspect S3 table schemas and sample data.")
    parser.add_argument(
        "--table",
        type=str,
        default="all",
        help=f"Table to inspect. Options: all, {', '.join(TABLE_PATHS.keys())}",
    )
    parser.add_argument("--limit", type=int, default=3, help="Row limit for sample (default: 3)")
    args = parser.parse_args()
    inspect_schemas(target_table=args.table, limit=args.limit)
