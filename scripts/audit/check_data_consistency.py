"""
Comprehensive Data Consistency & Quality Audit Script for OmniGuard AI Lakehouse.
Checks table schemas, counts, primary keys, foreign keys, null rates, anomalous values,
currency conversion logic, date offsets, and known data traps.
"""
import duckdb
import pandas as pd
import json

def audit_lakehouse():
    con = duckdb.connect("data/lakehouse.duckdb", read_only=True)
    tables = [t[0] for t in con.execute("SHOW TABLES").fetchall()]
    print(f"=== Tables Found ({len(tables)}) ===")
    print(tables)
    
    # 1. Table Counts & Deduplication impact
    print("\n" + "="*50)
    print("1. TABLE ROW COUNTS")
    print("="*50)
    counts = {}
    for t in tables:
        cnt = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        counts[t] = cnt
        print(f"  {t:35s}: {cnt:>10,d} rows")
        
    # Check deduplication drops
    if 'bronze_transactions' in counts and 'silver_transactions' in counts:
        trx_diff = counts['bronze_transactions'] - counts['silver_transactions']
        print(f"\n  Bronze -> Silver Transactions difference: {trx_diff} (quarantined: {counts.get('quarantine_duplicate_transactions', 0)})")
    if 'bronze_customers' in counts and 'silver_customers' in counts:
        cust_diff = counts['bronze_customers'] - counts['silver_customers']
        print(f"  Bronze -> Silver Customers difference: {cust_diff}")
    if 'bronze_products' in counts and 'silver_products' in counts:
        prod_diff = counts['bronze_products'] - counts['silver_products']
        print(f"  Bronze -> Silver Products difference: {prod_diff}")
    if 'bronze_complaints' in counts and 'silver_complaints' in counts:
        comp_diff = counts['bronze_complaints'] - counts['silver_complaints']
        print(f"  Bronze -> Silver Complaints difference: {comp_diff}")

    # 2. Primary Key Uniqueness
    print("\n" + "="*50)
    print("2. PRIMARY KEY UNIQUENESS CHECKS")
    print("="*50)
    pk_checks = [
        ("silver_customers", "customer_id"),
        ("silver_products", "product_id"),
        ("silver_transactions", "transaction_id"),
        ("silver_complaints", "complaint_id"),
        ("gold_customers", "customer_id"),
        ("gold_transactions", "transaction_id"),
    ]
    for tbl, pk in pk_checks:
        if tbl in tables:
            total = con.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
            distinct = con.execute(f"SELECT COUNT(DISTINCT {pk}) FROM {tbl}").fetchone()[0]
            nulls = con.execute(f"SELECT COUNT(*) FROM {tbl} WHERE {pk} IS NULL").fetchone()[0]
            status = "PASS" if total == distinct and nulls == 0 else "FAIL"
            print(f"  [{status}] {tbl}.{pk}: Total={total:,}, Distinct={distinct:,}, Nulls={nulls}")
            if total != distinct:
                dups = con.execute(f"""
                    SELECT {pk}, count(*) as cnt 
                    FROM {tbl} 
                    GROUP BY {pk} 
                    HAVING count(*) > 1 
                    LIMIT 5
                """).fetchall()
                print(f"     Sample duplicate PKs: {dups}")

    # 3. Foreign Key / Referential Integrity
    print("\n" + "="*50)
    print("3. FOREIGN KEY & REFERENTIAL INTEGRITY")
    print("="*50)
    
    # silver_transactions -> silver_customers
    res = con.execute("""
        SELECT COUNT(*) FROM silver_transactions t
        LEFT JOIN silver_customers c ON t.customer_id = c.customer_id
        WHERE c.customer_id IS NULL
    """).fetchone()[0]
    print(f"  silver_transactions with orphan customer_id: {res:,} / {counts.get('silver_transactions', 0):,}")

    # silver_transactions -> silver_products
    res = con.execute("""
        SELECT COUNT(*) FROM silver_transactions t
        LEFT JOIN silver_products p ON t.product_id = p.product_id
        WHERE p.product_id IS NULL
    """).fetchone()[0]
    print(f"  silver_transactions with orphan product_id: {res:,} / {counts.get('silver_transactions', 0):,}")

    # silver_transactions where customer_id doesn't match product's customer_id
    res = con.execute("""
        SELECT COUNT(*) FROM silver_transactions t
        JOIN silver_products p ON t.product_id = p.product_id
        WHERE t.customer_id != p.customer_id
    """).fetchone()[0]
    print(f"  silver_transactions where trx.customer_id != prod.customer_id: {res:,}")

    # silver_products -> silver_customers
    res = con.execute("""
        SELECT COUNT(*) FROM silver_products p
        LEFT JOIN silver_customers c ON p.customer_id = c.customer_id
        WHERE c.customer_id IS NULL
    """).fetchone()[0]
    print(f"  silver_products with orphan customer_id: {res:,} / {counts.get('silver_products', 0):,}")

    # silver_complaints -> silver_customers
    res = con.execute("""
        SELECT COUNT(*) FROM silver_complaints comp
        LEFT JOIN silver_customers c ON comp.customer_id = c.customer_id
        WHERE c.customer_id IS NULL
    """).fetchone()[0]
    print(f"  silver_complaints with orphan customer_id: {res:,} / {counts.get('silver_complaints', 0):,}")

    # silver_complaints -> affected_product_id analysis
    res_null = con.execute("SELECT COUNT(*) FROM silver_complaints WHERE affected_product_id IS NULL").fetchone()[0]
    res_not_null = counts.get('silver_complaints', 0) - res_null
    res_orphan_prod = con.execute("""
        SELECT COUNT(*) FROM silver_complaints comp
        LEFT JOIN silver_products p ON comp.affected_product_id = p.product_id
        WHERE comp.affected_product_id IS NOT NULL AND p.product_id IS NULL
    """).fetchone()[0]
    res_mismatched_cust = con.execute("""
        SELECT COUNT(*) FROM silver_complaints comp
        JOIN silver_products p ON comp.affected_product_id = p.product_id
        WHERE comp.customer_id != p.customer_id
    """).fetchone()[0]
    print(f"  silver_complaints affected_product_id:")
    print(f"    - Null: {res_null:,} ({res_null/max(1, counts.get('silver_complaints', 1))*100:.1f}%)")
    print(f"    - Non-null but product doesn't exist: {res_orphan_prod:,}")
    print(f"    - Non-null and exists, but product belongs to ANOTHER customer: {res_mismatched_cust:,} / {res_not_null:,} ({res_mismatched_cust/max(1, res_not_null)*100:.1f}%)")

    # 4. Exchange Rates & Currency Normalization
    print("\n" + "="*50)
    print("4. EXCHANGE RATES & CURRENCY NORMALIZATION")
    print("="*50)
    rates_sample = con.execute("SELECT * FROM gold_exchange_rates").fetchall()
    print("  gold_exchange_rates contents:")
    for r in rates_sample:
        print(f"    {r}")
    
    raw_rates_distinct = con.execute("""
        SELECT DISTINCT source_currency, target_currency, min(exchange_rate), max(exchange_rate), min(date), max(date)
        FROM bronze_daily_exchange_rates
        GROUP BY source_currency, target_currency
    """).fetchall()
    print("  bronze_daily_exchange_rates summary:")
    for r in raw_rates_distinct:
        print(f"    {r[0]} -> {r[1]}: min={r[2]}, max={r[3]}, dates {r[4]} to {r[5]}")

    # Check transactions currencies and amount_usd vs amount_usd
    trx_curr = con.execute("""
        SELECT 
            t.currency,
            COUNT(*) as count,
            COUNT(s.amount_usd) as has_raw_amount_usd,
            COUNT(t.amount_usd) as has_norm_amount_usd,
            MIN(t.amount), MAX(t.amount), AVG(t.amount),
            MIN(t.amount_usd), MAX(t.amount_usd), AVG(t.amount_usd)
        FROM gold_transactions t
        JOIN silver_transactions s ON t.transaction_id = s.transaction_id
        GROUP BY t.currency
    """).fetchall()
    print("  gold_transactions currency & normalization check:")
    for c in trx_curr:
        print(f"    Currency {c[0]}: count={c[1]:,}, raw_usd_cnt={c[2]:,}, norm_usd_cnt={c[3]:,}")
        print(f"      amount range: [{c[4]}, {c[5]}], avg={c[6]:.2f}")
        print(f"      norm_usd range: [{c[7]}, {c[8]}], avg={c[9]:.2f}")

    # Check if any amount_usd is NULL or <= 0
    bad_amounts = con.execute("""
        SELECT COUNT(*) FROM gold_transactions 
        WHERE amount_usd IS NULL OR amount_usd <= 0
    """).fetchone()[0]
    print(f"  gold_transactions with invalid/null amount_usd: {bad_amounts}")

    # 5. Dates, Timestamps, and Policy Window Check
    print("\n" + "="*50)
    print("5. DATES, TIMESTAMPS & 60-DAY POLICY WINDOW")
    print("="*50)
    date_summary = con.execute("""
        SELECT 
            MIN(transaction_date), MAX(transaction_date),
            MIN(process_date), MAX(process_date),
            MIN(days_since_transaction), MAX(days_since_transaction),
            COUNT(CASE WHEN is_within_60_days THEN 1 END) as within_60d,
            COUNT(CASE WHEN NOT is_within_60_days THEN 1 END) as outside_60d,
            COUNT(CASE WHEN days_since_transaction < 0 THEN 1 END) as future_dates
        FROM gold_transactions
    """).fetchone()
    print(f"  gold_transactions transaction_date: {date_summary[0]} to {date_summary[1]}")
    print(f"  gold_transactions process_date:      {date_summary[2]} to {date_summary[3]}")
    print(f"  days_since_transaction range:       [{date_summary[4]}, {date_summary[5]}]")
    print(f"  within 60 days:                     {date_summary[6]:,}")
    print(f"  outside 60 days:                    {date_summary[7]:,}")
    print(f"  future dates (< 0 days):            {date_summary[8]:,}")

    # Check time offset: process_date vs date(transaction_date - 6h)
    offset_check = con.execute("""
        SELECT 
            COUNT(*) as total,
            COUNT(CASE WHEN CAST(process_date AS DATE) = CAST(transaction_date AS DATE) THEN 1 END) as plain_cast_match,
            COUNT(CASE WHEN CAST(process_date AS DATE) = CAST(transaction_date - INTERVAL 6 HOUR AS DATE) THEN 1 END) as minus_6h_match
        FROM gold_transactions
    """).fetchone()
    print(f"  Process date alignment over {offset_check[0]:,} rows:")
    print(f"    - plain cast DATE(transaction_date) matches process_date: {offset_check[1]:,} ({offset_check[1]/offset_check[0]*100:.2f}%)")
    print(f"    - DATE(transaction_date - 6h) matches process_date:       {offset_check[2]:,} ({offset_check[2]/offset_check[0]*100:.2f}%)")

    # Customer registration date vs transaction date
    res_reg_trx = con.execute("""
        SELECT COUNT(*) 
        FROM gold_transactions t
        JOIN gold_customers c ON t.customer_id = c.customer_id
        WHERE CAST(t.transaction_date AS DATE) < CAST(c.registration_date AS DATE)
    """).fetchone()[0]
    print(f"  Transactions occurring BEFORE customer registration_date: {res_reg_trx:,}")

    # 6. Categoricals, Enums & Value Drift
    print("\n" + "="*50)
    print("6. CATEGORICALS, ENUMS & VALUE DRIFT")
    print("="*50)
    for col in ['transaction_status', 'transaction_country', 'transaction_type', 'channel']:
        vals = con.execute(f"SELECT {col}, COUNT(*) FROM gold_transactions GROUP BY {col} ORDER BY 2 DESC").fetchall()
        print(f"  gold_transactions.{col}: {vals}")

    vals = con.execute("SELECT product_type, product_status, COUNT(*) FROM silver_products GROUP BY 1, 2 ORDER BY 3 DESC").fetchall()
    print(f"  silver_products types & statuses: {vals}")

    vals = con.execute("SELECT country, segment, customer_status, COUNT(*) FROM silver_customers GROUP BY 1, 2, 3 ORDER BY 4 DESC LIMIT 10").fetchall()
    print(f"  silver_customers sample slices: {vals}")

    vals = con.execute("SELECT category, subcategory, status, COUNT(*) FROM silver_complaints GROUP BY 1, 2, 3 ORDER BY 4 DESC LIMIT 10").fetchall()
    print(f"  silver_complaints top categories/subcategories: {vals}")

    # 7. Fraud Score Leakage & Target Distribution
    print("\n" + "="*50)
    print("7. FRAUD LABELS & LEAKAGE CHECK")
    print("="*50)
    fraud_summary = con.execute("""
        SELECT 
            is_fraud,
            COUNT(*) as count,
            MIN(fraud_score) as min_score,
            MAX(fraud_score) as max_score,
            AVG(fraud_score) as avg_score
        FROM gold_transactions
        GROUP BY is_fraud
    """).fetchall()
    for f in fraud_summary:
        print(f"  is_fraud={f[0]}: count={f[1]:,}, min_score={f[2]}, max_score={f[3]}, avg_score={f[4]:.2f}")

    # 8. Null Rates across Gold and Silver tables
    print("\n" + "="*50)
    print("8. NULL VALUE ANALYSIS ACROSS TABLES")
    print("="*50)
    for tbl in ['silver_customers', 'silver_products', 'silver_transactions', 'silver_complaints', 'gold_customers', 'gold_transactions']:
        if tbl not in tables:
            continue
        cols = [c[0] for c in con.execute(f"DESCRIBE {tbl}").fetchall()]
        total_rows = con.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        null_cols = []
        for col in cols:
            n_null = con.execute(f"SELECT COUNT(*) FROM {tbl} WHERE {col} IS NULL").fetchone()[0]
            if n_null > 0:
                null_cols.append((col, n_null, n_null/total_rows*100))
        print(f"  {tbl} ({total_rows:,} rows):")
        if not null_cols:
            print("    No NULL values in any column.")
        else:
            for c, n, p in null_cols:
                print(f"    - {c:25s}: {n:>7,d} nulls ({p:5.1f}%)")

    # 9. Gold Customers Features Sanity Check
    print("\n" + "="*50)
    print("9. GOLD CUSTOMERS FEATURES CHECK")
    print("="*50)
    cust_feat = con.execute("""
        SELECT 
            MIN(account_age_days), MAX(account_age_days), AVG(account_age_days),
            COUNT(CASE WHEN account_age_days < 0 THEN 1 END) as negative_age,
            COUNT(CASE WHEN is_account_mature THEN 1 END) as mature_accounts,
            MIN(complaints_last_90d), MAX(complaints_last_90d), AVG(complaints_last_90d),
            MIN(active_products), MAX(active_products), AVG(active_products),
            COUNT(CASE WHEN active_products = 0 THEN 1 END) as zero_active_prod
        FROM gold_customers
    """).fetchone()
    print(f"  account_age_days range: [{cust_feat[0]}, {cust_feat[1]}], avg={cust_feat[2]:.1f}, negative={cust_feat[3]}")
    print(f"  mature accounts: {cust_feat[4]:,} / {counts.get('gold_customers', 0):,}")
    print(f"  complaints_last_90d range: [{cust_feat[5]}, {cust_feat[6]}], avg={cust_feat[7]:.3f}")
    print(f"  active_products range: [{cust_feat[8]}, {cust_feat[9]}], avg={cust_feat[10]:.2f}, zero_active={cust_feat[11]:,}")

    con.close()
    print("\n" + "="*50)
    print("AUDIT COMPLETE")
    print("="*50)

if __name__ == "__main__":
    audit_lakehouse()
