"""
S3 Connectivity & Health Verification Tool.
Tests both boto3 API access and DuckDB httpfs SQL querying over the S3 bucket.
"""
import os
import boto3
import duckdb
from dotenv import load_dotenv

load_dotenv()

def verify_connection():
    aws_access_key_id = os.getenv("AWS_ACCESS_KEY_ID")
    aws_secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY")
    region = os.getenv("AWS_DEFAULT_REGION", "us-east-2")
    bucket = os.getenv("S3_BUCKET_NAME")

    print("=" * 60)
    print("S3 CONNECTIVITY & LAKEHOUSE ACCESS DIAGNOSTIC")
    print("=" * 60)

    # 1. Environment variables
    print("[1/3] Checking environment configuration...")
    if not aws_access_key_id or not aws_secret_access_key or not bucket:
        print("  [FAIL] Missing AWS credentials or S3_BUCKET_NAME in .env")
        return False
    print(f"  [OK] Bucket: {bucket} (Region: {region})")
    print(f"  [OK] AWS Key: {aws_access_key_id[:4]}...{aws_access_key_id[-4:]}")

    # 2. Boto3 API connectivity
    print("\n[2/3] Testing boto3 API connectivity & listing prefixes...")
    try:
        s3 = boto3.client(
            "s3",
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            region_name=region,
        )
        prefixes = [
            "data/customers.csv",
            "data/products.csv",
            "data/complaints/",
            "data/transactions/",
            "data/call_center_interactions/",
        ]
        for p in prefixes:
            resp = s3.list_objects_v2(Bucket=bucket, Prefix=p, MaxKeys=1)
            found = len(resp.get("Contents", [])) > 0
            status_text = "[FOUND]" if found else "[MISSING]"
            print(f"  - {p:35s} {status_text}")
        print("  [OK] Boto3 client successfully authenticated and listed bucket.")
    except Exception as e:
        print(f"  [FAIL] Boto3 connection error: {e}")
        return False

    # 3. DuckDB HTTPFS connectivity
    print("\n[3/3] Testing DuckDB HTTPFS engine querying...")
    try:
        con = duckdb.connect()
        con.execute("INSTALL httpfs; LOAD httpfs;")
        con.execute(f"SET s3_region='{region}';")
        con.execute(f"SET s3_access_key_id='{aws_access_key_id}';")
        con.execute(f"SET s3_secret_access_key='{aws_secret_access_key}';")

        res = con.execute(f"SELECT count(*) FROM read_csv_auto('s3://{bucket}/data/branches.csv')").fetchone()
        print(f"  [OK] DuckDB read branches.csv successfully: {res[0]} branches found.")
    except Exception as e:
        print(f"  [FAIL] DuckDB HTTPFS error: {e}")
        return False

    print("\n" + "=" * 60)
    print("ALL S3 DIAGNOSTICS PASSED SUCCESSFULLY")
    print("=" * 60)
    return True

if __name__ == "__main__":
    verify_connection()
