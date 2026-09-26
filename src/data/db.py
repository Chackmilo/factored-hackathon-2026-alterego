"""
Database connection and session management for OmniGuard AI Lakehouse using DuckDB.
"""
import os
import duckdb
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

DEFAULT_DB_PATH = Path("data/lakehouse.duckdb")

def get_db_connection(db_path: Path = DEFAULT_DB_PATH, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """
    Returns a DuckDB connection to the local lakehouse.
    Ensures data directory exists.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path), read_only=read_only)
    
    # Configure S3 extensions if credentials exist
    aws_key = os.getenv("AWS_ACCESS_KEY_ID")
    aws_secret = os.getenv("AWS_SECRET_ACCESS_KEY")
    aws_region = os.getenv("AWS_DEFAULT_REGION", "us-east-2")
    
    if aws_key and aws_secret and not read_only:
        try:
            con.execute("INSTALL httpfs; LOAD httpfs;")
            con.execute(f"SET s3_region='{aws_region}';")
            con.execute(f"SET s3_access_key_id='{aws_key}';")
            con.execute(f"SET s3_secret_access_key='{aws_secret}';")
        except Exception:
            pass  # httpfs might already be loaded or offline
            
    return con
