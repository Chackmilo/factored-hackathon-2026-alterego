import os
import duckdb
from dotenv import load_dotenv

load_dotenv()

aws_access_key_id = os.getenv("AWS_ACCESS_KEY_ID")
aws_secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY")
region = os.getenv("AWS_DEFAULT_REGION", "us-east-2")
bucket = os.getenv("S3_BUCKET_NAME")

con = duckdb.connect()
con.execute("INSTALL httpfs; LOAD httpfs;")
con.execute(f"SET s3_region='{region}';")
con.execute(f"SET s3_access_key_id='{aws_access_key_id}';")
con.execute(f"SET s3_secret_access_key='{aws_secret_access_key}';")

tables = {
    "daily_exchange_rates": f"s3://{bucket}/data/daily_exchange_rates.csv",
    "customers": f"s3://{bucket}/data/customers.csv",
    "products": f"s3://{bucket}/data/products.csv",
    "sample_transaction": f"s3://{bucket}/data/transactions/year=2026/month=06/day=01/transactions_20260601.csv",
    "sample_complaint": f"s3://{bucket}/data/complaints/year=2026/month=06/day=01/complaints_20260601.csv"
}

for name, s3_path in tables.items():
    print(f"\n==================== {name} ====================")
    df = con.execute(f"SELECT * FROM read_csv_auto('{s3_path}') LIMIT 3;").df()
    print("Columns:", list(df.columns))
    print(df.to_dict(orient="records"))
