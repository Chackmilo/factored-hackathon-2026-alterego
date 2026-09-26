import os
import duckdb
from dotenv import load_dotenv

load_dotenv()
con = duckdb.connect()
con.execute("INSTALL httpfs; LOAD httpfs;")
con.execute("SET s3_region='us-east-2';")
con.execute(f"SET s3_access_key_id='{os.getenv('AWS_ACCESS_KEY_ID')}';")
con.execute(f"SET s3_secret_access_key='{os.getenv('AWS_SECRET_ACCESS_KEY')}';")

bucket = os.getenv("S3_BUCKET_NAME")
df = con.execute(f"SELECT * FROM read_csv_auto('s3://{bucket}/data/call_center_interactions/year=2025/month=03/*/*.csv') LIMIT 5").df()
print("Columns in call_center_interactions:")
print(df.columns.tolist())
print("\nSample row:")
print(df.iloc[0].to_dict())
