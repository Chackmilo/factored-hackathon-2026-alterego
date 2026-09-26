import os
import duckdb
from dotenv import load_dotenv

load_dotenv()

bucket = os.getenv("S3_BUCKET_NAME")
aws_key = os.getenv("AWS_ACCESS_KEY_ID")
aws_secret = os.getenv("AWS_SECRET_ACCESS_KEY")
region = os.getenv("AWS_DEFAULT_REGION", "us-east-2")

print(f"Connecting to S3 bucket: {bucket}")
con = duckdb.connect()
con.execute("INSTALL httpfs; LOAD httpfs;")
con.execute(f"SET s3_region='{region}';")
con.execute(f"SET s3_access_key_id='{aws_key}';")
con.execute(f"SET s3_secret_access_key='{aws_secret}';")

try:
    res = con.execute(f"SELECT count(*) FROM read_csv_auto('s3://{bucket}/data/call_center_interactions/year=2025/month=03/*/*.csv')").fetchone()
    print("S3 query successful! Count:", res[0])
except Exception as e:
    print("Error querying S3:", e)
