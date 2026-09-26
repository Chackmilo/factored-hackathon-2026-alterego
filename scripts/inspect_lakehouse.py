import duckdb

con = duckdb.connect("data/lakehouse.duckdb", read_only=True)
tables = [t[0] for t in con.execute("SHOW TABLES").fetchall()]
print("Tables in lakehouse.duckdb:", tables)

for t in ["bronze_complaints", "gold_transactions", "gold_customers", "gold_exchange_rates"]:
    if t in tables:
        cols = [c[0] for c in con.execute(f"DESCRIBE {t}").fetchall()]
        print(f"\n{t} columns ({len(cols)}):", cols)
        cnt = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        print(f"Row count: {cnt}")
