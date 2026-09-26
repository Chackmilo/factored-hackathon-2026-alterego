import os
import duckdb
from dotenv import load_dotenv

load_dotenv()

aws_access_key_id = os.getenv("AWS_ACCESS_KEY_ID")
aws_secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY")
region = os.getenv("AWS_DEFAULT_REGION", "us-east-2")
bucket = os.getenv("S3_BUCKET_NAME")

con = duckdb.connect()

print("Installing & loading httpfs...")
con.execute("INSTALL httpfs;")
con.execute("LOAD httpfs;")

con.execute(f"SET s3_region='{region}';")
con.execute(f"SET s3_access_key_id='{aws_access_key_id}';")
con.execute(f"SET s3_secret_access_key='{aws_secret_access_key}';")

print("\n--- Testing query on branches.csv ---")
df_branches = con.execute(f"SELECT * FROM read_csv_auto('s3://{bucket}/data/branches.csv') LIMIT 3;").df()
print(df_branches)

print("\n--- Testing query on a single complaints partition ---")
sample_complaint_path = f"s3://{bucket}/data/complaints/year=2023/month=06/day=17/complaints_20230617.csv"
df_complaints = con.execute(f"SELECT * FROM read_csv_auto('{sample_complaint_path}') LIMIT 3;").df()
print(df_complaints.columns.tolist())
print(df_complaints.head(2))
