import os
import boto3
from dotenv import load_dotenv

load_dotenv()

aws_access_key_id = os.getenv("AWS_ACCESS_KEY_ID")
aws_secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY")
region_name = os.getenv("AWS_DEFAULT_REGION", "us-east-2")
bucket_name = os.getenv("S3_BUCKET_NAME")

s3 = boto3.client(
    "s3",
    aws_access_key_id=aws_access_key_id,
    aws_secret_access_key=aws_secret_access_key,
    region_name=region_name,
)

print(f"Connected to {bucket_name}")

fact_tables = [
    "data/complaints/",
    "data/transactions/",
    "data/call_center_interactions/",
    "data/call_transcripts/",
    "data/satisfaction_surveys/",
]

for ft in fact_tables:
    print(f"\n--- Sample objects in {ft} ---")
    resp = s3.list_objects_v2(Bucket=bucket_name, Prefix=ft, MaxKeys=4)
    for item in resp.get("Contents", []):
        print(f"  {item['Key']} ({item['Size']:,} bytes)")
