# nextGen GL — Budget Journal Entry Import & Mapping Guide

**Purpose:** Standalone reference for mapping customer budget source data into nextGen GL **Journal Entry** import files for:

1. **Budget Adoption**
2. **Budget Amendment**
3. **Budget Transfer**

Use this document in any data/ETL/migration repo. No application codebase access required.

**Audience:** Data migration teams, implementation consultants, ETL developers  
**Version:** 1.0 · August 2026  
**Related:** `GL-IMPORT-VALIDATIONS.md` (full GL template catalog)

---

## Critical facts (read first)

| Fact | Detail |
|------|--------|
| **There is no separate Budget import template** | Budgets are loaded via **`JOURNAL_ENTRY`** |
| **`templateType`** | `JOURNAL_ENTRY` |
| **Import UI** | Journal Entry Inquiry → Import |
| **File format** | CSV (UTF-8), max **200 MB** |
| **Sync row limit (JE Inquiry)** | **500 rows** — larger files must use **async** |
| **Revised budget formula** | `Adopted + Amendments + Transfers` |
| **Load order** | Adoption → Amendment → Transfer |

---

## Table of contents

1. [Recommended load order](#1-recommended-load-order)
2. [Instance readiness checklist](#2-instance-readiness-checklist)
3. [Classify source data into 3 budget types](#3-classify-source-data-into-3-budget-types)
4. [Correct CSV template](#4-correct-csv-template)
5. [Global mapping rules](#5-global-mapping-rules)
6. [Budget Adoption mapping](#6-budget-adoption-mapping)
7. [Budget Amendment mapping](#7-budget-amendment-mapping)
8. [Budget Transfer mapping](#8-budget-transfer-mapping)
9. [Valid JE type combinations](#9-valid-je-type-combinations)
10. [Validation gates (must pass before upload)](#10-validation-gates-must-pass-before-upload)
11. [Pre-import validation checklist](#11-pre-import-validation-checklist)
12. [ETL transformation recipes](#12-etl-transformation-recipes)
13. [Blank mapping worksheets](#13-blank-mapping-worksheets)
14. [Sample files](#14-sample-files)
15. [Common failures & fixes](#15-common-failures--fixes)
16. [Delivery & remapping workflow](#16-delivery--remapping-workflow)

---

## 1. Recommended load order

```
Prerequisites (already on target instance)
  ├─ Segment Codes          (COA_SEGMENT)
  ├─ Valid Code Combinations (COA_ACCOUNTS)  ← budgetingAllowed = true on budgeted accounts
  ├─ Org units, JE sources enabled
  └─ Fiscal calendar with OPEN periods
           ↓
1. Budget Adoption JEs     (Ledger Type = Budget Adoption)
           ↓
2. Budget Amendment JEs    (Ledger Type = Budget Amendment)
           ↓
3. Budget Transfer JEs     (Ledger Type = Budget Transfer)
           ↓
Verify in Budget / GL Balance Inquiry:
  Revised Budget = Adopted + Amendments + Transfers
```

### Why this order?

| Type | Role |
|------|------|
| **Adoption** | Base adopted budget for the fiscal year |
| **Amendment** | Increases / decreases after adoption |
| **Transfer** | Moves budget between accounts (usually nets to zero across the JE) |

If the source system only has a **final revised** amount and **no history**, load everything as **Budget Adoption** (simplest path). Split into Amendment / Transfer only when historical fidelity is required.

---

## 2. Instance readiness checklist

Complete **before** mapping source → CSV.

| # | Check | Where | Failure if skipped |
|---|-------|-------|--------------------|
| 1 | COA segment codes exist | Chart of Accounts | Accounting String not found |
| 2 | Accounting strings (COA accounts) exist | Valid Code Combinations | Tier 3 line failure |
| 3 | Budgeted accounts have **`budgetingAllowed = true`** | Account config | Budget ledger type rejected |
| 4 | Accounts **active** + **postingAllowed** (as required by date) | Account config | Line posting rejected |
| 5 | Organization units exist | GL Settings → Organization Units | Header org validation fail |
| 6 | Primary org unit set | GL Settings | Blank Organization Name fails if no primary |
| 7 | JE Source **GL** and/or **BnP** enabled for entity | JE Source Settings | Invalid JE source |
| 8 | JE Type combo exists (Ledger + Source + TransactionType) | Master / JE Types | Invalid JE type combination |
| 9 | Fiscal year + **open** period for JournalDate | Fiscal calendar | Period closed / not found |
| 10 | Download official JE import template from UI | Import → template | Header mismatches |

**Action for ETL repo:** Export lookup tables from the target instance:

- Org unit **names**
- Enabled JE source **short labels** (`GL`, `BnP`, …)
- Sample of valid **Accounting String** values (or full COA export)
- Open fiscal period date ranges

---

## 3. Classify source data into 3 budget types

Map each source row (or source document) to exactly one import file type.

| Source signal (examples) | Target Ledger Type | Target TransactionType | Output file |
|--------------------------|--------------------|------------------------|-------------|
| Original budget, adopted budget, beginning budget, FY open budget | `Budget Adoption` | `Budget Adoption` | `budget_adoption.csv` |
| Supplemental, mid-year increase/decrease, ordinance amendment | `Budget Amendment` | `Budget Amendment` | `budget_amendment.csv` |
| Inter-account / inter-dept move, reallocation, transfer | `Budget Transfer` | `Budget Transfer` | `budget_transfer.csv` |
| Only final revised balance, no history | `Budget Adoption` | `Budget Adoption` | `budget_adoption.csv` |

### Decision tree

```
Does source distinguish adoption vs amendment vs transfer?
  NO  → Put all amounts in Budget Adoption file
  YES →
        Is it the original / opening budget?
          YES → Budget Adoption
          NO  →
                Is it a move between accounts (offsetting +/−)?
                  YES → Budget Transfer
                  NO  → Budget Amendment
```

---

## 4. Correct CSV template

### Full official header row (exact spelling)

Copy this header **exactly** (case-sensitive). Do **not** “fix” typos in the official template.

```
Group ID, External JE number, Ledger Type, TransactionType, JournalDate, Action Type, Accounting String, DebitAmount, CreditAmount, Tender Comment, Acquisition Cost, Acquisition Date, Asset Description, Asset IDt, Bank Account, Benefit Type, Budget ID, Budget Name, Check Date, Check No, Contract ID, Customer ID, Customer Name, Date Paid, Depreciation Method, Depreciation Period, Disposal Date, Disposal Method, Earnings Code, Employee ID, Fee Label, Gain/Loss, Grant ID, Invoice Date, Invoice No, Pay Method, Payment Date, Payment ID, Payment Type, Payroll Disbursement, PO Number, Position Code, Processed By, Receipt Category, Receipt Category Description, Reciept ID, Record Type, Request ID, Requestor ID, Sale Amount, Tender Type, Useful Life, Vendor ID, Vendor Name, Version, JE Source Value, Organization Name, JE Description, JE Line Description
```

> Note: `Reciept ID` and `Asset IDt` are spelled as shown in the official template.

### Minimum columns for budget imports

ETL may output only these columns (extra official columns can be omitted if blank; missing **required** columns fail Tier 1).

| CSV Header | Required for budgets | Notes |
|------------|----------------------|-------|
| **Group ID** | **Yes** (esp. async) | Same value = one journal entry |
| External JE number | Recommended | Unique per JE if provided; blank = auto |
| **Ledger Type** | **Yes** | `Budget Adoption` / `Budget Amendment` / `Budget Transfer` |
| **TransactionType** | **Yes** | Match ledger (or `Manual` with valid combo) |
| **JournalDate** | **Yes** | `M/D/YYYY` or `MM/DD/YYYY` |
| **Accounting String** | **Yes** | Must exist on instance; budgetingAllowed |
| **DebitAmount** | Line | Debit **or** credit, not both |
| **CreditAmount** | Line | Debit **or** credit, not both |
| **JE Source Value** | Recommended | Default if blank often `GL`; prefer explicit `GL` or `BnP` |
| Organization Name | Optional | Blank → primary org unit |
| JE Description | Recommended | Header narrative |
| JE Line Description | Recommended | Line narrative |

### Minimal header (practical ETL output)

```csv
Group ID,External JE number,Ledger Type,TransactionType,JournalDate,Accounting String,DebitAmount,CreditAmount,JE Source Value,Organization Name,JE Description,JE Line Description
```

---

## 5. Global mapping rules

Apply to **all three** budget files.

### CSV / file rules

| Rule | Requirement |
|------|-------------|
| Encoding | UTF-8 |
| Headers | Exact names; case-sensitive |
| Empty rows | Remove |
| Max size | 200 MB |
| Sync (JE UI) | ≤ 500 rows |
| Async | Use for > 500 rows; **Group ID column required** |

### Dates

| Rule | Value |
|------|-------|
| Format | `M/D/YYYY` or `MM/DD/YYYY` |
| Valid | `10/1/2025`, `01/15/2026` |
| Invalid | `2025-10-01`, `01/15/26`, `15/01/2026`, `Oct 1 2025` |

```
Source: 2025-10-01  →  Target: 10/1/2025
Source: 20251001    →  Target: 10/1/2025
```

### Amounts

| Rule | Requirement |
|------|-------------|
| No currency symbol | `50000.00` not `$50000.00` |
| No thousands separator | `1000.00` not `1,000.00` |
| Max 2 decimal places | `100.50` |
| Non-negative per cell | Use debit **or** credit side to express direction |
| One side per line | Debit > 0 **or** Credit > 0, **never both** on same line |
| JE must balance | Σ DebitAmount = Σ CreditAmount **within each Group ID** |

### Strings

| Rule | Requirement |
|------|-------------|
| Trim whitespace | Always |
| Do not use placeholders | Convert `NULL`, `N/A`, `-`, `#N/A` → blank |
| Accounting String | Must match instance COA format exactly (including separators) |
| Ledger / TransactionType | Exact display names (matching is case-insensitive at runtime, but prefer Title Case as below) |

### Defaults (if source blank)

| Column | Default if blank |
|--------|------------------|
| JE Source Value | `GL` |
| Organization Name | Primary org unit |
| TransactionType | Prefer explicit budget type; `Manual` only if JE type combo allows it |
| Ledger Type | **Do not leave blank for budgets** — set explicitly |

### JE Source short labels (use these in CSV)

| Short Label | Meaning | Use for budgets? |
|-------------|---------|------------------|
| `GL` | General Ledger | **Yes (recommended default)** |
| `BnP` | Budget & Performance | **Yes** (if enabled on entity) |
| `BR` | Bank Reconciliation | **No** (not budget) |
| `AP`, `AR`, `PR`, … | Other subledgers | Only if JE type combo exists |

---

## 6. Budget Adoption mapping

### Fixed values

| Field | Value |
|-------|-------|
| Ledger Type | `Budget Adoption` |
| TransactionType | `Budget Adoption` (preferred) **or** `Manual` if using GL + Manual combo |
| JE Source Value | `GL` or `BnP` |

### Source → target column map

| Source concept | Target CSV header | Transformation | Required | Validation gate |
|----------------|-------------------|----------------|----------|-----------------|
| Document / batch / JE id | Group ID | Stable unique key; same for all lines of one JE | Yes | Groups lines; async requires column |
| Source JE / ordinance # | External JE number | Trim; unique across imports if set | No | Uniqueness on instance |
| *(fixed)* | Ledger Type | Always `Budget Adoption` | Yes | Valid ledger + JE type |
| *(fixed)* | TransactionType | `Budget Adoption` | Yes | Valid JE type combo |
| Budget effective / adoption date | JournalDate | To `M/D/YYYY`; must be in open period | Yes | Open fiscal period |
| Account / COA string | Accounting String | Map via COA/crosswalk; exact instance format | Yes | Exists; budgetingAllowed |
| Budget amount (expense increase / asset) | DebitAmount | Absolute number, 2 dp; blank credit | Line | Debit XOR credit |
| Budget amount (offset / revenue / contra) | CreditAmount | Absolute number, 2 dp; blank debit | Line | Debit XOR credit |
| *(fixed or entity)* | JE Source Value | `GL` or `BnP` | Yes* | Source enabled |
| Org / entity name | Organization Name | Exact org unit name; blank → primary | No | Org exists |
| Budget title / narrative | JE Description | Trim; ≤ practical length | No | — |
| Line / account description | JE Line Description | Trim | No | — |

\* Prefer always populated.

### Balancing pattern (Adoption)

Government budgets usually need an **offset line** so the JE balances.

**Pattern A — Expense budgets with single offset account**

```
Line 1..N: Debit  = budget amount on expense/object accounts
Line last: Credit = total of debits on budget offset / fund balance / control account
```

**Pattern B — Revenue budgets**

```
Line 1..N: Credit = budget amount on revenue accounts
Line last: Debit  = total of credits on offset account
```

**Pattern C — Source already provides balanced pairs**

Keep source debit/credit as-is after cleaning amounts.

### Adoption output file naming

```
budget_adoption_FY{yy}_{entity}.csv
```

---

## 7. Budget Amendment mapping

### Fixed values

| Field | Value |
|-------|-------|
| Ledger Type | `Budget Amendment` |
| TransactionType | `Budget Amendment` (preferred) **or** `Manual` |
| JE Source Value | `GL` or `BnP` |

### Source → target column map

| Source concept | Target CSV header | Transformation | Required | Validation gate |
|----------------|-------------------|----------------|----------|-----------------|
| Amendment doc / batch id | Group ID | Unique per amendment JE | Yes | Grouping |
| Amendment number | External JE number | Unique if set | No | Uniqueness |
| *(fixed)* | Ledger Type | `Budget Amendment` | Yes | JE type |
| *(fixed)* | TransactionType | `Budget Amendment` | Yes | JE type |
| Amendment effective date | JournalDate | `M/D/YYYY` in open period | Yes | Open period |
| Account | Accounting String | Exact COA | Yes | budgetingAllowed |
| Increase amount | DebitAmount **or** CreditAmount | Follow entity debit/credit convention | Line | XOR + balance |
| Decrease amount | Opposite side | Absolute value on opposite side | Line | XOR + balance |
| Source | JE Source Value | `GL` / `BnP` | Yes* | Enabled |
| Org | Organization Name | Exact name or blank | No | Org exists |
| Narrative | JE Description / JE Line Description | Trim | No | — |

### Sign / direction conventions

| Business meaning | Typical mapping (expense accounts) |
|------------------|-------------------------------------|
| Increase expense budget | DebitAmount = amount |
| Decrease expense budget | CreditAmount = amount |
| Increase revenue budget | CreditAmount = amount |
| Decrease revenue budget | DebitAmount = amount |

Always confirm entity chart conventions; **the JE must still balance**.

### Prerequisites

- Adoption loaded (or intentional amendment-only load approved)
- Same COA / budgetingAllowed rules as Adoption

### Amendment output file naming

```
budget_amendment_FY{yy}_{entity}.csv
```

---

## 8. Budget Transfer mapping

### Fixed values

| Field | Value |
|-------|-------|
| Ledger Type | `Budget Transfer` |
| TransactionType | `Budget Transfer` (preferred) **or** `Manual` |
| JE Source Value | `GL` or `BnP` |

### Source → target column map

| Source concept | Target CSV header | Transformation | Required | Validation gate |
|----------------|-------------------|----------------|----------|-----------------|
| Transfer id / batch | Group ID | One transfer = one Group ID | Yes | Grouping + balance |
| Transfer number | External JE number | Unique if set | No | Uniqueness |
| *(fixed)* | Ledger Type | `Budget Transfer` | Yes | JE type |
| *(fixed)* | TransactionType | `Budget Transfer` | Yes | JE type |
| Transfer date | JournalDate | `M/D/YYYY` open period | Yes | Open period |
| From account | Accounting String | Exact COA | Yes | budgetingAllowed |
| To account | Accounting String | Exact COA (other line) | Yes | budgetingAllowed |
| Transfer amount | Debit on “to” / Credit on “from” (typical) | Absolute; opposite sides | Yes | ΣD = ΣC |
| Source | JE Source Value | `GL` / `BnP` | Yes* | Enabled |
| Org | Organization Name | Exact or blank | No | Org exists |
| Narrative | JE Description / JE Line Description | Trim | No | — |

### Typical 2-line transfer

```
Line 1 (TO account):   DebitAmount  = amount, CreditAmount blank
Line 2 (FROM account): CreditAmount = amount, DebitAmount blank
```

Transfers should balance within the Group ID (often exactly 2 lines; multi-line splits allowed if ΣD = ΣC).

### Transfer output file naming

```
budget_transfer_FY{yy}_{entity}.csv
```

---

## 9. Valid JE type combinations

CSV values must form a **valid JE Type** on the instance.

### Preferred combinations for budgets

| Ledger Type | JE Source Value | TransactionType |
|-------------|-----------------|-----------------|
| Budget Adoption | `GL` | Budget Adoption |
| Budget Amendment | `GL` | Budget Amendment |
| Budget Transfer | `GL` | Budget Transfer |
| Budget Adoption | `BnP` | Budget Adoption |
| Budget Amendment | `BnP` | Budget Amendment |
| Budget Transfer | `BnP` | Budget Transfer |

### Also valid (if using Manual)

| Ledger Type | JE Source Value | TransactionType |
|-------------|-----------------|-----------------|
| Budget Adoption | `GL` | Manual |
| Budget Amendment | `GL` | Manual |
| Budget Transfer | `GL` | Manual |

### Do **not** use

| Invalid pattern | Why |
|-----------------|-----|
| Budget Adoption + Encumbrance Booking | Wrong transaction family |
| Ledger Type blank / `Actuals` for budget load | Posts to wrong ledger buckets |
| JE Source `BR` for budgets | `BR` = Bank Reconciliation, not Budget |
| Mixing Ledger Types inside one Group ID | Header fields come from first row of the group — keep consistent |

**Header consistency rule:** For every row sharing a Group ID, keep the same:

- Ledger Type  
- TransactionType  
- JournalDate  
- JE Source Value  
- Organization Name  
- External JE number  
- JE Description  

---

## 10. Validation gates (must pass before upload)

These mirror what nextGen GL enforces at import (Tier 1 format + Tier 3 business).

### Tier 1 — format / schema (ETL must prevent)

| Gate ID | Check | Pass criteria |
|---------|-------|---------------|
| T1-01 | Required columns present | Group ID, JournalDate, Accounting String, Ledger Type, amounts present as needed |
| T1-02 | Header spelling | Exact template names |
| T1-03 | Date format | `M/D/YYYY` or `MM/DD/YYYY` |
| T1-04 | Amount format | Numeric, ≤ 2 decimals, no `$` / `,` |
| T1-05 | Debit XOR Credit | Not both populated > 0 on same line |
| T1-06 | No empty data rows | Strip blank lines |
| T1-07 | Async Group ID | Column present for async mode |

### Tier 3 — business / master data (ETL must pre-validate against instance lookups)

| Gate ID | Check | Pass criteria |
|---------|-------|---------------|
| T3-01 | Org unit | Blank or exact name on instance |
| T3-02 | JE Source enabled | `GL` / `BnP` (or chosen source) enabled |
| T3-03 | Ledger Type valid | Exact: Budget Adoption / Amendment / Transfer |
| T3-04 | TransactionType valid | Matches combo table |
| T3-05 | JE Type combo | Ledger + Source + TransactionType exists |
| T3-06 | Fiscal period open | JournalDate in an **open** period |
| T3-07 | External JE number | Unique if provided |
| T3-08 | Accounting String exists | Present in COA on instance |
| T3-09 | Account active / config valid for date | Valid for JournalDate |
| T3-10 | **budgetingAllowed = true** | Required for all three budget ledger types |
| T3-11 | Posting rules | Account allows posting as configured |
| T3-12 | JE balanced | Σ Debit = Σ Credit per Group ID |
| T3-13 | Header consistency | Same header fields within Group ID |
| T3-14 | No NET_ACCOUNT on lines | Do not use net/system accounts as lines if restricted |
| T3-15 | Async atomicity | Any failed group can reject batch — fix all groups before re-import |

### Cross-file / sequencing gates

| Gate ID | Check |
|---------|-------|
| SEQ-01 | COA (segments + accounts) imported before any budget JE |
| SEQ-02 | Adoption file imported before Amendment / Transfer (unless amendment-only approved) |
| SEQ-03 | Amendment before Transfer when both exist and transfers assume amended base |
| SEQ-04 | After import: spot-check Revised = Adopted + Amendments + Transfers |

---

## 11. Pre-import validation checklist

Run against each mapped CSV (`budget_adoption.csv`, `budget_amendment.csv`, `budget_transfer.csv`).

### File-level

- [ ] UTF-8 CSV
- [ ] Headers match section 4
- [ ] No empty rows
- [ ] File ≤ 200 MB
- [ ] Row count ≤ 500 **or** async mode selected
- [ ] Async ⇒ Group ID column present
- [ ] One Ledger Type value only in the file (do not mix Adoption/Amendment/Transfer in one file)

### Per Group ID

- [ ] ≥ 2 lines (unless entity allows single-line with auto-balance — assume **manual balance required**)
- [ ] Σ DebitAmount = Σ CreditAmount (tolerance 0.00)
- [ ] Ledger Type / TransactionType / JournalDate / JE Source / Org / External JE # / JE Description identical on all lines
- [ ] JournalDate in open period lookup
- [ ] External JE number unique (if set)

### Per line

- [ ] Accounting String in COA lookup
- [ ] Account budgetingAllowed = true
- [ ] Exactly one of DebitAmount / CreditAmount > 0
- [ ] Amount ≥ 0, ≤ 2 decimals
- [ ] JE Source + Ledger + TransactionType in allowed combo list

### Sequencing

- [ ] Adoption ready / imported first
- [ ] Then Amendment
- [ ] Then Transfer

---

## 12. ETL transformation recipes

Pseudo-logic for the data repo.

### 12.1 Normalize amounts

```
function cleanAmount(raw):
  if raw is null/blank/N/A → return blank
  s = string(raw).trim()
  s = remove "$" and ","
  n = toDecimal(s)
  if n < 0 → treat as opposite side (see signedAmountToSides)
  return round(n, 2)
```

### 12.2 Signed amount → debit/credit

```
function signedAmountToSides(amount, convention):
  # convention examples: "expense_increase_is_debit"
  if amount > 0:
    return { DebitAmount: amount, CreditAmount: "" }
  if amount < 0:
    return { DebitAmount: "", CreditAmount: abs(amount) }
  drop or skip zero lines
```

### 12.3 Build Group ID

```
Group ID = "{TYPE_PREFIX}-{SOURCE_DOC_ID}"
  Adoption:  BA-{doc}
  Amendment: BAM-{doc}
  Transfer:  BT-{doc}
```

All lines for one balanced journal share the same Group ID.

### 12.4 Ensure JE balance

```
for each Group ID:
  debitSum = sum(DebitAmount)
  creditSum = sum(CreditAmount)
  if debitSum != creditSum:
    if OFFSET_ACCOUNT configured:
      post difference to OFFSET_ACCOUNT on the short side
    else:
      FAIL mapping (do not import unbalanced JE)
```

### 12.5 Date convert

```
JournalDate = format(parse(sourceDate), "M/D/YYYY")
assert JournalDate in OPEN_PERIODS
```

### 12.6 Accounting string resolve

```
Accounting String =
  if source already nextGen format → use as-is after trim
  else → CROSSWALK[sourceAccount] → nextGen Accounting String
assert Accounting String in COA_LOOKUP
assert COA_LOOKUP[string].budgetingAllowed == true
```

### 12.7 Emit three files

```
write budget_adoption.csv   where type == ADOPTION
write budget_amendment.csv  where type == AMENDMENT
write budget_transfer.csv   where type == TRANSFER
# never mix Ledger Types in one file
```

---

## 13. Blank mapping worksheets

Fill these in the data repo for each customer.

### 13.1 Adoption worksheet

**Source file:** _______________________  
**templateType:** `JOURNAL_ENTRY`  
**Output:** `budget_adoption.csv`  
**Depends on:** COA_SEGMENT, COA_ACCOUNTS (`budgetingAllowed=true`), open periods  

| Source column | Source example | Target CSV header | Transformation rule | Required | Validation gate |
|---------------|----------------|-------------------|---------------------|----------|-----------------|
| | | Group ID | | Yes | T1-01, group consistency |
| | | External JE number | | No | T3-07 |
| *(constant)* | | Ledger Type | `Budget Adoption` | Yes | T3-03, T3-05 |
| *(constant)* | | TransactionType | `Budget Adoption` | Yes | T3-04, T3-05 |
| | | JournalDate | → M/D/YYYY | Yes | T1-03, T3-06 |
| | | Accounting String | COA/crosswalk | Yes | T3-08..T3-11 |
| | | DebitAmount | cleanAmount | Line | T1-04, T1-05, T3-12 |
| | | CreditAmount | cleanAmount | Line | T1-04, T1-05, T3-12 |
| *(constant)* | | JE Source Value | `GL` or `BnP` | Yes | T3-02, T3-05 |
| | | Organization Name | exact org name | No | T3-01 |
| | | JE Description | trim | No | Header consistency |
| | | JE Line Description | trim | No | — |

**Offset account (if needed):** _______________________  
**Open period range used:** _______________________  
**Estimated rows / groups:** _______________________  
**Import mode:** sync (≤500) / async  

### 13.2 Amendment worksheet

**Source file:** _______________________  
**Output:** `budget_amendment.csv`  

| Source column | Source example | Target CSV header | Transformation rule | Required | Validation gate |
|---------------|----------------|-------------------|---------------------|----------|-----------------|
| | | Group ID | BAM-… | Yes | |
| | | External JE number | | No | |
| *(constant)* | | Ledger Type | `Budget Amendment` | Yes | |
| *(constant)* | | TransactionType | `Budget Amendment` | Yes | |
| | | JournalDate | → M/D/YYYY | Yes | |
| | | Accounting String | | Yes | budgetingAllowed |
| | | DebitAmount | | Line | |
| | | CreditAmount | | Line | |
| *(constant)* | | JE Source Value | `GL` / `BnP` | Yes | |
| | | Organization Name | | No | |
| | | JE Description | | No | |
| | | JE Line Description | | No | |

**Depends on:** Adoption loaded (recommended)  

### 13.3 Transfer worksheet

**Source file:** _______________________  
**Output:** `budget_transfer.csv`  

| Source column | Source example | Target CSV header | Transformation rule | Required | Validation gate |
|---------------|----------------|-------------------|---------------------|----------|-----------------|
| | | Group ID | BT-… | Yes | |
| | | External JE number | | No | |
| *(constant)* | | Ledger Type | `Budget Transfer` | Yes | |
| *(constant)* | | TransactionType | `Budget Transfer` | Yes | |
| | | JournalDate | → M/D/YYYY | Yes | |
| From acct | | Accounting String | credit side typically | Yes | |
| To acct | | Accounting String | debit side typically | Yes | |
| Amount | | DebitAmount / CreditAmount | absolute; opposite sides | Yes | ΣD=ΣC |
| *(constant)* | | JE Source Value | `GL` / `BnP` | Yes | |
| | | Organization Name | | No | |
| | | JE Description | | No | |
| | | JE Line Description | | No | |

---

## 14. Sample files

### 14.1 Budget Adoption

```csv
Group ID,External JE number,Ledger Type,TransactionType,JournalDate,Accounting String,DebitAmount,CreditAmount,JE Source Value,Organization Name,JE Description,JE Line Description
BA-001,SRC-BA-001,Budget Adoption,Budget Adoption,10/1/2025,100-4100-01,50000.00,,GL,,FY26 Adopted Budget,Police Salaries
BA-001,SRC-BA-001,Budget Adoption,Budget Adoption,10/1/2025,100-4200-01,25000.00,,GL,,FY26 Adopted Budget,Fire Salaries
BA-001,SRC-BA-001,Budget Adoption,Budget Adoption,10/1/2025,100-3000-00,,75000.00,GL,,FY26 Adopted Budget,Budget Offset
```

### 14.2 Budget Amendment

```csv
Group ID,External JE number,Ledger Type,TransactionType,JournalDate,Accounting String,DebitAmount,CreditAmount,JE Source Value,Organization Name,JE Description,JE Line Description
BAM-001,SRC-BAM-001,Budget Amendment,Budget Amendment,1/15/2026,100-4100-01,5000.00,,GL,,Mid-year amendment #1,Increase Police
BAM-001,SRC-BAM-001,Budget Amendment,Budget Amendment,1/15/2026,100-3000-00,,5000.00,GL,,Mid-year amendment #1,Budget Offset
```

### 14.3 Budget Transfer

```csv
Group ID,External JE number,Ledger Type,TransactionType,JournalDate,Accounting String,DebitAmount,CreditAmount,JE Source Value,Organization Name,JE Description,JE Line Description
BT-001,SRC-BT-001,Budget Transfer,Budget Transfer,3/1/2026,100-4200-01,2000.00,,GL,,Q3 budget transfer,To Fire
BT-001,SRC-BT-001,Budget Transfer,Budget Transfer,3/1/2026,100-4100-01,,2000.00,GL,,Q3 budget transfer,From Police
```

---

## 15. Common failures & fixes

| Symptom / error theme | Likely cause | Fix in mapping |
|-----------------------|--------------|----------------|
| Accounting String not found | COA not loaded / wrong format | Import COA first; fix separators/crosswalk |
| budgeting not allowed / budgetingAllowed | Account config false | Set budgetingAllowed=true on account config **or** exclude account |
| Invalid JE type / combination | Wrong Ledger + Source + TxnType | Use section 9 combos |
| Period closed / not found | Bad date or closed period | Use open period date; open period in GL |
| JE must be balanced | ΣD ≠ ΣC in Group ID | Add offset line or fix amounts |
| Both debit and credit | Mapped both sides | Keep one side only |
| `$1,000.00` / commas | Dirty amounts | Strip `$` and `,` |
| Date `2025-10-01` | Wrong format | Convert to `10/1/2025` |
| Org unit not found | Name mismatch | Map to exact instance name or leave blank |
| Duplicate External JE number | Reused source id | Make unique or leave blank |
| Async batch all rejected | One group failed | Fix all groups; async is all-or-none per batch |
| Used `BR` as budget source | Wrong short label | Use `GL` or `BnP` |
| Mixed ledger types in one Group ID | Bad grouping | Split files; one ledger type per Group ID |
| Import before COA | Sequencing | Follow section 1 |

---

## 16. Delivery & remapping workflow

### In the data / ETL repo

1. Import this markdown as the mapping contract.
2. Fill worksheets (§13) from customer source columns.
3. Build lookup tables from target GL instance (orgs, COA, open periods, enabled sources).
4. Generate **three** CSVs (or one Adoption-only if no history).
5. Run pre-import checklist (§11) in CI or a validation script.
6. Deliver files + a short manifest:

```text
entity: <name>
fiscalYear: <FY>
files:
  - budget_adoption.csv
  - budget_amendment.csv   # optional
  - budget_transfer.csv    # optional
templateType: JOURNAL_ENTRY
importOrder: adoption → amendment → transfer
jeSource: GL
rowCounts: { adoption: N, amendment: N, transfer: N }
validation: PASSED | FAILED
```

### In nextGen GL

1. Confirm readiness checklist (§2).
2. Import Adoption (sync if ≤500 rows, else async).
3. Verify adopted balances.
4. Import Amendment.
5. Import Transfer.
6. Confirm Revised Budget inquiry.

### On errors

1. Download `{filename}_errors.csv` (sync) or job error file (async).
2. Classify Tier 1 vs Tier 3.
3. Fix transformation / lookups in ETL.
4. Re-validate checklist.
5. Re-import failed groups only (new External JE numbers if prior partial success).

---

## Quick reference card

| Question | Answer |
|----------|--------|
| Which template? | `JOURNAL_ENTRY` |
| Separate budget template? | **No** |
| Load Adoption first? | **Yes** |
| Then Amendment? | **Yes** |
| Then Transfer? | **Yes** |
| Ledger Type values | `Budget Adoption`, `Budget Amendment`, `Budget Transfer` |
| TransactionType values | Same names (or `Manual` with GL) |
| JE Source | `GL` or `BnP` |
| Date format | `M/D/YYYY` |
| Must balance? | **Yes**, per Group ID |
| Account flag required? | **`budgetingAllowed = true`** |
| COA first? | **Yes** |

---

*Standalone migration document for nextGen GL budget journal imports. Safe to copy into external data-mapping repositories.*
