# Fraud risk model v1: transfer from the IEEE-CIS Fraud Detection competition

Status: proposal of 28 September, pending the mentors' answer to TQ-026. It replaces the training
recipe of brief decision 3 (`docs/TEAM_BRIEF_COMPLEMENTED.md`), not its feature discipline. The
policy clause `POL-ESC-ML-RISK` and the `RiskScorer` interface stay as they are.

## 1. Why we bring an external competition

Sections 5 and 6 of `docs/technical-discuss-points.md` established, on the full history (4,425,008
transactions, 4,316 flags), that `is_fraud` moves with nothing: no transaction attribute, no
customer attribute, no claim, no compensation, no call. The leak-free model and the rules baseline
sit at ROC AUC 0.50 on 1.5 M held-out rows, and `fraud_score` is a function of the label (uniform
0 to 30 when not fraud, uniform 0 to 100 when fraud). There is no learnable target in the data as
delivered, so a model trained here can only learn noise.

The IEEE-CIS Fraud Detection competition (Kaggle, 2019, data by Vesta Corporation) offers what
the dataset lacks: 590,540 labeled card-not-present transactions with 20,663 fraud rows (3.5%),
a public winning recipe, and a metric (ROC AUC) we already report. The hackathon rules allow
pretrained and external components as long as the rigor is shown (AGENTS.md section 4, judging
of "component selection, leakage prevention, held-out evaluation, error analysis").

The idea is a transfer, not a copy: train on the competition data a model that sees only features
we can compute on our charges, validate it on the competition's own time-based holdout, then serve
it on our charges through a shared feature contract. Our data is used to calibrate the escalation
threshold as a percentile, never to train (its label is random).

## 2. The competition in one page

Two tables joined on `TransactionID`.

| Group | Columns | Official meaning (Vesta) |
| --- | --- | --- |
| Target | `isFraud` | 1 when the transaction was reported as fraud (chargeback and the client's later transactions) |
| Time | `TransactionDT` | Seconds from a reference datetime, not a timestamp |
| Amount | `TransactionAmt` | Amount in USD |
| Product | `ProductCD` | Product code of the purchase (W, H, C, S, R; meaning undisclosed) |
| Card | `card1` to `card6` | Card identifiers: issuer, type, category (credit or debit), network |
| Address | `addr1`, `addr2` | Billing region and billing country of the purchaser |
| Distance | `dist1`, `dist2` | Distances between billing address, mailing address, zip, IP, phone area |
| Email | `P_emaildomain`, `R_emaildomain` | Purchaser and recipient email domains |
| Counts | `C1` to `C14` | Counts such as how many addresses or phones are associated with the card |
| Time deltas | `D1` to `D15` | Days between events, for example days since the card's first transaction |
| Matches | `M1` to `M9` | Match flags, for example names on the card and the address agree |
| Vesta features | `V1` to `V339` | Engineered ranking, counting and entity-relation features |
| Identity | `id_01` to `id_38`, `DeviceType`, `DeviceInfo` | Network and device information, present on 24% of rows |

Metric: ROC AUC. The first-place recipe (Chris Deotte and team) rests on three things: the data
has no client id, so the team built one from `card1`, `addr1` and the normalized `D1` (day of
the transaction minus `D1`, the day the card started); it then aggregated amounts, counts and
deltas per client id, respecting time; and it ensembled CatBoost, LightGBM and XGBoost trained
on a time split (private leaderboard 0.9459). The lesson that transfers is the client id
aggregation: in our data the client id is native (`customer_id` and `product_id`), so the
strongest features of the competition are the cheapest ones for us.

Sources: the competition page (kaggle.com/competitions/ieee-fraud-detection), the first-place
writeup on the same site, and the NVIDIA technical blog "Leveraging Machine Learning to Detect
Fraud: Tips to Developing a Winning Kaggle Solution".

## 3. Variable mapping: competition to LATAM Bank

Feasibility measured on 28 September on the full lakehouse (`data/lakehouse_full.duckdb`) and the
auxiliary tables (`data/lakehouse_aux.duckdb`).

| Competition | Our source | Contract feature | Feasibility |
| --- | --- | --- | --- |
| `isFraud` | `silver_transactions.is_fraud` | training label on Kaggle only | Ours is random (section 5); used only to report agreement, never to train |
| `TransactionDT` | `transaction_date` minus 6 h (processing clock), `process_date` | `hour_sin`, `hour_cos`, `day_of_week` | Full |
| `TransactionAmt` | `amount_usd` (fixed at silver, `amount_usd_source`) | `amount_usd`, `log_amount_usd` | Full; both in USD |
| `TransactionAmt` decimal part | `amount` in the local currency | `amount_has_cents` | Weak: COP has no cents, MXN and ARS do |
| `ProductCD` | `transaction_type` x `product_type` | none | Vocabularies differ and the meaning of W, H, C, S, R is undisclosed; excluded from the transfer model |
| `card1` (card id) | `product_id` | key for the per-card aggregations | Full, and better: ours is a real key, theirs was reconstructed |
| `card4` (network) | none | none | Our bank is the issuer; no network column |
| `card6` (credit or debit) | `silver_products.product_type` (Tarjeta Crédito, Tarjeta Débito, accounts) | `card_kind` in {credit, debit, account} | Full |
| `addr1`, `addr2` | `silver_customers.city`, `country` | inputs to the mismatch features | Full (3 countries, 16 cities) |
| `dist1`, `dist2` | `transaction_city` and `transaction_country` versus the customer's city and country; `latitude`, `longitude` are 81% null | `address_distance_bucket` in {same city, same country, other country} | Partial: a bucket, not a distance; 4.7% of charges are abroad |
| `P_emaildomain` | `silver_customers.email` domain (7 domains) | `email_domain_freq` | Full but flat: the seven domains are uniform |
| `R_emaildomain` | none | none | No counterparty field, also for transfers |
| `C1` to `C14` | counts per card and per customer over earlier rows | `tx_count_card_1d`, `tx_count_card_7d`, `tx_count_card_30d`, `tx_count_customer_7d`, `cards_per_customer` | Full; the current `velocity_*` features are this |
| `D1` (days since the card started) | `process_date` minus `silver_products.opening_date` | `card_age_days` | Full |
| other `D` columns | days since the card's previous transaction, since the customer's previous transaction | `days_since_prev_tx_card`, `days_since_prev_tx_customer` | Full |
| `M1` to `M9` | consistency checks: country match, city match, currency equals the product currency, currency belongs to the transaction country | `consistency_matches` (share of checks passed) | Partial: four checks against nine flags |
| `V1` to `V339` | per-card and per-customer aggregations of the amount over earlier rows | `amount_mean_card_hist`, `amount_std_card_hist`, `amount_zscore_card`, `ratio_to_historical_avg` | Full; this is the "uid aggregation" recipe |
| `id_*`, `DeviceType`, `DeviceInfo` | `digital_events` (platform, browser, is_mobile, ip_country, session_id) | none | Not linkable: of 205,943 Web and App charges of 2026, 170 have an event of the same customer within one hour and none on the same product the same day; `ip_country` never differs from the home country |
| card-not-present (implicit: every competition row) | `channel` in {Web, App} | `card_not_present` | Constant on Kaggle, so the model cannot learn it; see the limitation in section 6 |

Bank-only inputs with no competition analog stay out of the transfer model and feed the rules
baseline and the risk explanation: `segment`, `credit_score`, `account_age_days` (tenure),
`credit_limit` utilization, `days_past_due`, `has_linked_app`, `merchant_category` (78% null),
`merchant_name` (24 values), `branch_id`, calls and complaints in the 30 days before the charge.

Excluded everywhere, as leakage or post-authorization: `is_fraud`, `fraud_score`,
`transaction_status`, `response_code`, every complaint resolution field, `product_status` after
the charge, and anything dated after the charge's processing timestamp.

## 4. Feature contract v1

One builder, `build_contract_features(frame, source)`, produces the same columns from either
source. Every feature is computed from the card's or the customer's earlier rows only (sorted by
time, current row excluded), so serving a charge never looks ahead. Null policy: medians from the
training split, stored in the model bundle.

| Feature | Definition | Kaggle | Ours |
| --- | --- | --- | --- |
| `amount_usd` | amount in USD, clipped at 0 | `TransactionAmt` | `amount_usd` |
| `log_amount_usd` | log1p of the above | derived | derived |
| `amount_has_cents` | 1 when the local amount has a fractional part | `TransactionAmt` | `amount` |
| `hour_sin`, `hour_cos` | hour of the processing clock | `TransactionDT` mod 86,400 | `transaction_date` minus 6 h |
| `day_of_week` | 0 to 6 | `TransactionDT` div 86,400 | `process_date` |
| `card_kind` | credit, debit, account (one-hot) | `card6` | `product_type` |
| `card_age_days` | days since the card started | `D1` | `opening_date` |
| `days_since_prev_tx_card` | days since the card's previous row | uid and `TransactionDT` | `product_id` and `process_date` |
| `days_since_prev_tx_customer` | days since the customer's previous row | uid | `customer_id` |
| `tx_count_card_1d`, `_7d`, `_30d` | earlier rows of the card in the window | uid | `product_id` |
| `tx_sum_card_7d` | USD charged by the card in 7 days | uid | `product_id` |
| `tx_count_customer_7d` | earlier rows of the customer in 7 days | uid (same as card) | `customer_id` |
| `cards_per_customer` | distinct cards seen for the customer so far | uid grouping of `card1` | `silver_products` |
| `amount_mean_card_hist`, `amount_std_card_hist` | expanding mean and std of the card's earlier amounts | uid | `product_id` |
| `amount_zscore_card` | (amount minus mean) over std, 0 when fewer than 3 rows | derived | derived |
| `ratio_to_historical_avg` | amount over the customer's expanding mean | uid | `customer_id` |
| `address_distance_bucket` | 0 same city, 1 same country, 2 other country | `dist1` is 0, small, large; `addr2` differs | city and country comparison |
| `consistency_matches` | share of match checks that pass | count of T over the non-null `M` flags | four checks |
| `email_domain_freq` | frequency of the email domain in the training source | `P_emaildomain` | customer email domain |
| `card_not_present` | 1 for Web and App | constant 1 | `channel` |

On Kaggle the uid is `card1`, `addr1` and the normalized `D1`, exactly as the winning solution
built it, so the aggregations are comparable to ours.

## 5. Training and validation

1. Time split on `TransactionDT` (last 20% of the days held out), the same rule as the current
   `train()` in `src/ml/fraud_risk.py`. Metrics: ROC AUC, PR AUC, recall at the cost-weighted
   threshold (10 x missed fraud, 1 x unnecessary verification), same report format.
2. Two ablations on the holdout: without the per-card aggregations (measures how much the "uid
   recipe" brings) and without `card_not_present` and `email_domain_freq` (the two features we
   trust least on our side).
3. Adversarial validation between the Kaggle rows and a sample of our charges, both expressed in
   the contract: a classifier that tells the sources apart with AUC near 0.5 means the feature
   distributions overlap; a high AUC names the features that shift, and those are dropped or
   binned before serving. This is the honest measure of the domain gap and goes in the report.
4. On our charges the model has no label to score against, so validation is behavioral: fixtures
   with a foreign, high, bursty charge on an old card must score above a routine charge of the same
   customer; the tests pin these orderings. The flat agreement with `is_fraud` is reported once as
   a non-result, as in section 5 of the discussion doc.
5. Model: HistGradientBoosting today, LightGBM once the ONNX runtime row of `docs/PLAN.md` lands;
   the competition's ensemble is out of scope for the hackathon.

## 6. How the agent tools use it from now on

- `RiskScorer.__call__(matched, history, profile) -> (ml_risk_score, top_features)` keeps its
  signature; the orchestrator does not change. The bundle carries the contract version and the
  threshold.
- The threshold is a percentile of our own serving window, not the competition's probability:
  after publishing the serving copy, the score is computed over the disputable charges of the
  window and the cutoff for the top 2% is stored in the bundle. `POL-ESC-ML-RISK` compares
  `ml_risk_score` with that cutoff (today's constant 0.70 becomes `bundle["threshold"]`). Rationale:
  prevalence is 3.5% there and unknown here, so an absolute probability means nothing after the
  transfer; a percentile bounds the escalation volume the console can absorb.
- Risk explanation (secondary clauses, discussion doc 2.1): `FEATURE_PHRASES` extends to the
  contract, one customer-safe phrase per feature, and the top three contributions still travel in
  `risk_top_features`.
- Limitation stated in the report and the console: the competition holds card-not-present
  transactions only, so on POS, ATM and Branch charges the model would extrapolate. Since 3-Oct
  (AUD-27) the scorer rates only the channels its threshold was calibrated on (Web and App) and
  reports any other charge as not scored. The rules baseline (amount above 1,000 USD, ratio above
  3, foreign country) is measured offline only; at serving nothing scores those channels, and the
  policy's other escalations (`POL-ESC-500`, `POL-ESC-MULTI`) still apply to them.
- Leakage guards: `tests/test_fraud_risk.py` keeps asserting that `is_fraud` and `fraud_score`
  are absent from the contract, and a new test asserts that no feature reads a row dated after the
  charge.

## 7. Data handling

- A team member with a Kaggle account downloads `train_transaction.csv` and `train_identity.csv`
  after accepting the competition rules; the files land in `data/kaggle/` (git-ignored, next to the
  other raw data) and never enter a commit, a log or a prompt. The competition data is anonymized
  and public, and the same discipline applies as to the bank data (rule 10).
- The trained bundle is `models/fraud_risk_ieee.joblib` (git-ignored), with the JSON report in
  `reports/ml/` as today, plus the ablation and adversarial validation tables.
- Licence: the competition rules restrict the data to competition and non-commercial use; a
  hackathon submission fits, and TQ-026 asks the mentors to confirm.

## 8. Code plan (spec-driven, tests first; done on 29 September, commits 0f33f14 to 756fe10)

| File | Change | Red test |
| --- | --- | --- |
| `src/ml/feature_contract.py` | `CONTRACT_V1` list, `build_contract_features(frame, source)` | contract columns equal the list; a row's features do not change when a later row is added (no look-ahead) |
| `src/ml/ieee_cis_adapter.py` | column renames, uid construction, contract call | a 20-row synthetic frame with the competition's column names maps to the contract with the expected values |
| `src/ml/fraud_risk.py` | `--source kaggle` and `--source lakehouse`, ablations, adversarial validation, percentile threshold | report holds `fraud_score_used: no`, `threshold_kind: percentile`; the scorer orders the behavioral fixtures |
| `src/rules/dispute_policy.py` | threshold read from the input, default 0.70 kept | existing clause tests unchanged |
| `docs/technical-discuss-points.md` | section 7 | none |

## 9. Open question

TQ-026 (HITL console): confirm the IEEE-CIS transfer as the model of record, the competition data
licence for the submission, and the percentile threshold for `POL-ESC-ML-RISK`.

## 10. Results of notebook 05 (29 September): contract v1.1

`notebooks/05_ieee_cis_feature_homologation.ipynb` computed the contract of section 4 with one
definition per feature on the 590,540 competition rows and on the 4,425,008 bank charges (charts 18
to 21), and put every categorical level to Jev. What changes:

### 10.1 Numeric features

Signal is measured as the best of the plain and the binned univariate ROC AUC against the
competition label (the binned one catches U-shaped signals such as amount, which is 2.5% fraud in
the middle buckets and above 5% at both ends). Against the bank label every feature sits at 0.50,
as expected.

| Verdict | Features | Reason |
| --- | --- | --- |
| Keep as is | `hour_sin`, `card_kind_credit`, `card_kind_debit`, `card_age_days`, `consistency_matches` | Signal (AUC 0.56 to 0.62) and a domain AUC under 0.85 |
| Keep after per-source binning or ranking | `amount_usd`, `log_amount_usd`, `days_since_prev_tx_card`, `amount_mean_card_hist` | Signal (0.60 to 0.68) but the levels differ: median amount 69 versus 467 USD, days since the previous charge 1.9 versus 54, mean amount per card 79 versus 1,321 |
| Weak, decided by the ablation | `amount_has_cents`, `hour_cos`, `day_of_week`, the three `tx_count_card_*`, `tx_sum_card_7d`, `amount_std_card_hist`, `amount_zscore_card`, `ratio_to_historical_avg`, `address_distance_bucket` | Univariate signal under 0.55; the per-card counts, the competition's best group, only pay off in interaction with the others |
| Bank-only | `cards_per_customer` | One card per competition uid by construction |
| Drop | `card_not_present`, `email_domain_freq` | Constant on the competition side; constant on the bank side (seven uniform domains) and a fingerprint of the source |

Domain gap: an adversarial classifier separates the sources with AUC 1.000 under every encoding
tested: raw values with every feature, raw values without the fingerprint feature, per-source
percentile ranks with nulls filled by the source median, and the same ranks on the 14 continuous
features only. Ranks equalize each marginal, but tie masses do not move (charges per card in a day
is 0 on almost every bank row and on 70% of competition rows), so the source stays identifiable.
The gap cannot be transformed away; it is an e-commerce processor against a LATAM bank.
Consequences: the transferred probabilities carry no absolute meaning on the bank side (hence the
percentile threshold of section 6), the ablation tests the discrete block (address bucket, card
kind, cents, consistency) as a whole, and the report states the gap with these numbers.

### 10.2 Categorical levels (Jev, `jev-1.13.0`, 61 typed answers, cached in `notebooks/05_jev_level_homologation.json`)

| Competition variable | Homologated (confidence at or above 0.70) | No equivalent | Left to a human |
| --- | --- | --- | --- |
| `card6` | credit to Tarjeta Crédito (0.99), debit to Tarjeta Débito (0.99) | charge card, debit or credit | none |
| `card4` (network) | none | visa, mastercard, discover (0.84 to 0.92); american express split 0.52 versus Tarjeta Crédito 0.43 | none |
| `ProductCD` | none | C, H, R, S (0.81 to 0.83); W leans no_equivalent 0.63 versus Purchase 0.31 | W, if the team wants a purchase code |
| `DeviceType` | desktop to Desktop Web (0.80) | mobile (0.66; mass split between the apps and Mobile Web) | mobile |
| OS family (`id_30`) | Android (0.76), iOS (0.89), Mac OS X to MacOS (0.81) | other | Windows (0.63), Linux (0.49 versus Linux 0.42) |
| Browser family (`id_31`) | chrome, safari, firefox, edge, samsung browser (0.88 to 0.97) | internet explorer, opera, other | none |
| `P_emaildomain` (top 20) | gmail, yahoo, hotmail, icloud, outlook, live (0.99 to 1.00) | the ISP domains (aol, comcast, att, sbcglobal, verizon, cox, optonline, charter, bellsouth), anonymous.com, ymail | msn.com, yahoo.com.mx, me.com |

Coverage (Noul): Web 0.69 and App 0.60 are of the competition's kind; ATM, POS, Branch and
Transfer are not (0.03 to 0.05); no transaction type reaches 0.5 on its own (Purchase 0.43,
Payment 0.39). Serving rule: the transferred score is served on Web and App charges (30.0% of
all charges) and the rules baseline stays on the rest. The level tables of card kind, OS and
browser matter only if the identity features ever become linkable (they are not, section 3).

### 10.3 A bank data quirk found on the way

18.71% of charges predate the opening date of their product (median 321 days before, the same
share for every product type, 34% of the 2023 charges falling to 3% of the 2026 ones): product
opening dates were generated independently of the transactions. `card_age_days` is clipped at 0
and stays a weak feature on the bank side; the finding is recorded in AGENTS.md section 7.

## 11. Training results and the deploy rule (29 September)

Team decision of 29 September: **the trainer uses only the variables the deployed app can compute at scoring
time.** The serving copy (`supabase/migrations/0003_bank.sql`) holds customers (country, city), products (type,
currency, opening date) and transactions (time, amounts, channel, country, city). Every contract feature except
`card_age_days` is computable from the customer's own rows and profile; card age is excluded because the bank's
opening dates are independent of the charges (section 10.3), so its value at scoring time is noise. This is
`DEPLOYABLE_V1` in `src/ml/feature_contract.py` (19 features).

Run: `uv run python -m src.ml.fraud_risk_transfer --competition data/kaggle --lakehouse data/lakehouse_full.duckdb --out reports/ml --model models/fraud_risk_ieee.joblib`
(42 s; report in `reports/ml/fraud_risk_transfer.md`, bundle git-ignored).

| Measure | Value |
| --- | --- |
| Competition split | 487,837 train rows (17,150 fraud), 102,703 holdout rows (3,513 fraud), last 20% of the days held out |
| Holdout ROC AUC, PR AUC | 0.817, 0.165 |
| Ablation without the per-card aggregates | ROC AUC 0.785 |
| Ablation without the discrete block | ROC AUC 0.755 |
| Bank calibration | 75,366 Web and App charges in the 60 days to 2026-06-17; threshold = percentile 98 = 0.0669; 2.0% above |
| Agreement with `is_fraud` (73 flags in the window) | ROC AUC 0.507 (flat, as expected; reported, never optimized) |

For scale, the competition's winners reached 0.94 with 400 columns, the identity table and an ensemble; the
deployable contract keeps 19 columns and one gradient boosting model.

Wiring (commits 6c4454d and 756fe10): `DisputePolicyInput.ml_risk_threshold` (default 0.70) replaces the
hardcoded constant in `POL-ESC-ML-RISK`; the orchestrator passes the scorer's `policy_threshold` and the
handoff carries it; `load_scorer` in `src/api/dispute_routes.py` picks `TransferRiskScorer` for a bundle with a
contract version, and `FRAUD_MODEL_PATH` defaults to `models/fraud_risk_ieee.joblib`. The scorer computes the
features from the gateway rows and the profile; card age stays null, and the address and consistency features
fill from the columns the gateway returns (extending its query with `transaction_country` and
`transaction_city` is the one gateway change still open). The gateway should pass the customer's last 90 days
of charges so the 30-day aggregates are complete.
