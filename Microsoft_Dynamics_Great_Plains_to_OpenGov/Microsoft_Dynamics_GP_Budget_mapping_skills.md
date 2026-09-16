---
name: microsoft-dynamics-gp-budget-mapping
description: >-
  Maps Microsoft Dynamics GP budget masters, budget details, amendments, and
  transfers into OpenGov NextGen GL Journal Entry import CSVs. Use when
  transforming GP GL00200, GL00201, GL12000, GL12001, or GL32000 extracts into
  Budget Adoption, Budget Amendment, and Budget Transfer imports and validating
  COA, fiscal periods, journal balance, sequencing, and import readiness.
---

# Microsoft Dynamics GP Budget Mapping

## Purpose

Use this skill to map Great Plains budget source files into OpenGov NextGen GL
budget journal-entry imports outside the Sarasota repository.

The user may provide SQL tables, CSVs, Excel files, or Parquet extracts. Identify
the logical GP table represented by each file and map by column name, not by
repository path.

This skill covers:

- Budget Adoption
- Budget Amendment
- Budget Transfer
- GP-account to OpenGov-account transformation
- Journal Entry CSV generation
- OpenGov format, arithmetic, business, lookup, and sequencing validations
- Exclusions, reconciliation, and audit deliverables

## Critical rules

1. OpenGov budgets use the **Journal Entry** import. There is no separate budget
   import template.
2. Download the current Journal Entry template from the destination instance.
   Its headers and instructions override this file.
3. Load in semantic order: **Adoption → Amendment → Transfer**.
4. Never invent amendment or transfer history from a final revised balance.
5. Every Group ID must balance: total debits equal total credits.
6. Every imported account, including offsets, must exist and have
   `budgetingAllowed=true`.

## Template-version safeguard

Sarasota has multiple Journal Entry template versions:

- older budget files use `Organization Name`;
- newer GL files use `Organization Unit`;
- another documented UI template includes `JE Source Value` and other columns.

Use exactly one current destination template. Do not combine headers from old
versions. Preserve exact spelling, case, order, and official typos.

## Required source package

| GP source | Purpose | Required columns |
| --- | --- | --- |
| `GL00200` | Budget master | `YEAR1`, `BUDGETID`, `BUDCOMNT`, `From_Date`, `TODATE`, stable row ID/timestamp |
| `GL00201` | Budget amounts by period/account | `YEAR1`, `BUDGETID`, `PERIODID`, `PERIODDT`, `ACTINDX`, `ACTNUMBR_1..3`, `BUDGETAMT` |
| `GL32000` | Posted budget transaction history | `YEAR1`, `JRNENTRY`, `TRXDATE`, `PERIODDT`, `REFRENCE`, `BUDGETID`, `ACTINDX`, `BUDGETAMT`, `BudgerAdjustment` |
| `GL12001` | Open budget transaction lines | Same logical detail fields plus `BACHNUMB` |
| `GL12000` | Open budget transaction headers | `JRNENTRY`, `BACHNUMB`, `TRXDATE`, `REFRENCE` |
| `GL00100` | GP account master | `ACTINDX`, `ACTNUMBR_1..3`, `ACTDESCR`, `ACCTTYPE` and status fields |
| `GL00105` | Formatted legacy account, when available | `ACTINDX`, `ACTNUMST` |

`BudgerAdjustment` is the GP source column spelling used in the Sarasota
extract. Inspect the supplied schema and document any equivalent column name.

Do not use undated, duplicate-heavy staging data such as Sarasota `XLImport`
unless its grain, dates, transaction identity, and completeness are proven.

## Required destination references

Obtain current OpenGov exports or approved lookups for:

- Accounting strings and segment codes
- Account active/effective dates
- `budgetingAllowed`, `postingAllowed`, modules allowed, and system-account flags
- Fiscal-year and period date ranges, including open/closed status
- Organization units and primary-org behavior
- Enabled JE sources, normally `GL` or `BnP`
- Valid `(Ledger Type, JE Source, TransactionType)` combinations
- Existing External JE numbers
- Approved budget balancing/control account

These checks cannot be completed from GP files alone.

## Parameters

Record these before mapping:

```text
GP company:
Extraction timestamp:
Fiscal calendar:
Fiscal years/date scope:
OpenGov entity:
Template version/date:
Organization column and value:
JE source:
Balance tolerance:
Approved budget offset account:
COA crosswalk version:
```

Sarasota uses an October 1–September 30 fiscal year. Do not apply that calendar
to another GP company without confirmation.

## Source profiling and classification

Profile every source before transformation:

- row count and distinct key count;
- fiscal-year, budget-ID, period, and transaction-date ranges;
- duplicates by expected grain;
- null/invalid dates and account indexes;
- total `BUDGETAMT` and `BudgerAdjustment` by year and budget;
- whether `GL12000`, `GL12001`, and `GL32000` contain reliable history;
- whether multiple budget IDs represent original, revised, scenario, or inactive
  budgets.

Classify:

| Source evidence | OpenGov ledger |
| --- | --- |
| Original/adopted/opening budget | `Budget Adoption` |
| Supplemental increase or decrease that changes total budget | `Budget Amendment` |
| Offsetting move between accounts with zero net change | `Budget Transfer` |
| Final revised balance with no reliable event history | Adoption-only, with written approval |

Sarasota had one active `GL00201.BUDGETID` per FY and no rows in `GL12000`,
`GL12001`, or `GL32000`. Therefore FY2022–FY2026 final revised balances were
loaded as Budget Adoption. Amendment and Transfer outputs were header-only; no
transactions were fabricated.

## Global normalization

- Preserve IDs and account segments as text.
- Trim identifiers, descriptions, references, and crosswalk values.
- Remove `.0` introduced by spreadsheet numeric conversion.
- Zero-pad segments only according to the approved customer COA profile.
- Convert GP sentinel dates such as `1900-01-01` to null.
- Output dates in the current template format, normally `M/D/YYYY` or
  `MM/DD/YYYY`.
- Use decimal arithmetic and round output amounts to two decimals.
- Remove `$`, commas, and null placeholders.
- Express direction with a positive debit or positive credit, never a negative
  target amount.
- Remove blank rows and amounts that round to zero.
- Sort deterministically before assigning line numbers.

## Account mapping

### Build the legacy account

Preferred:

```text
GL00105.ACTNUMST joined by ACTINDX
```

Fallback:

```text
trim(ACTNUMBR_1) + "-" + trim(ACTNUMBR_2) + "-" + trim(ACTNUMBR_3)
```

Sarasota legacy accounts use `#####-##-###`; its OpenGov accounts use
`###-###-###-#####-######`. These formats are customer-specific.

### Resolution hierarchy

1. **EXACT** — approved full-account crosswalk.
2. **DERIVED** — independently approved object, department, program, fund, and
   project segment crosswalks.
3. **UNRESOLVED** — exclude from import and report.

Sarasota's derived profile builds:

```text
100-{OpenGov Department}-{OpenGov Program}-{OpenGov Object}-000000
```

Sarasota also has a specific department `14 → 210` exception. Neither rule is a
portable default.

The Sarasota budget Adoption import intentionally uses **EXACT matches only**.
Derived and suspense candidates go to the unmatched report. Apply the same
fail-closed policy unless the customer approves derived combinations and every
derived account is verified in OpenGov.

Never use a suspense account merely because it has a valid format.

### Crosswalk validations

- Each legacy account maps to at most one OpenGov account.
- No target account is malformed, blank, or duplicated unexpectedly.
- Every target combination exists and is active for JournalDate.
- Account type and budget behavior remain compatible.
- Every imported account has `budgetingAllowed=true`.
- Offset account is active, posting-allowed, budget-enabled, and approved.
- Mapping method and crosswalk version are retained in audit output.

## Budget Adoption mapping

### Source grain and transformation

1. Select approved `GL00201` fiscal years and budget IDs.
2. Construct the legacy account.
3. Group by fiscal year, budget ID, legacy account, and `ACTINDX`.
4. `Annual Amount = round(sum(BUDGETAMT), 2)`.
5. Drop Annual Amount = 0.
6. Join `GL00200` by fiscal year and budget ID.
7. Join `GL00100` by `ACTINDX` for description.
8. Keep only approved OpenGov account mappings.

### Target mapping

| Target column | Transformation |
| --- | --- |
| `Ledger Type` | `Budget Adoption` |
| `Group ID` | One stable group per approved FY/budget; Sarasota `BA-FY{YYYY}` |
| `External JE number` | Unique key; Sarasota `GP-BUDGET-{YYYY}-ADOPTION` |
| `JE Line Number` | Deterministic sequence within Group ID |
| `TransactionType` | `Budget Adoption`, or approved `Manual` combination |
| `JournalDate` | `GL00200.From_Date` |
| `Accounting String` | Approved OpenGov account |
| `DebitAmount` | Annual Amount when positive |
| `CreditAmount` | Absolute Annual Amount when negative |
| `Budget ID`, `Budget Name` | Populate only when current template expects them |
| Organization column | Exact target org, or blank only when primary default is confirmed |
| `JE Description` | FY/budget narrative; Sarasota states final revised GP budget loaded as adoption |
| `JE Line Description` | `GL00100.ACTDESCR`, fallback legacy account/budget ID |

### Adoption balancing

After excluding unresolved accounts:

```text
residual = sum(DebitAmount) - sum(CreditAmount)
if residual > 0: offset CreditAmount = residual
if residual < 0: offset DebitAmount  = abs(residual)
```

Add no line when residual is zero. The offset account must be explicitly
approved. Sarasota maps GP control account `10400-00-000` to
`100-100-000-10502-000000`; do not reuse either account elsewhere by default.

Recalculate the offset after all exclusions. Never use an offset to hide source
errors, duplicate rows, or an incorrect COA mapping.

## Budget Amendment mapping

### Build transaction history

Union:

- posted rows from `GL32000`;
- open rows from `GL12001`, left joined to `GL12000` on
  `JRNENTRY + BACHNUMB`.

For each row:

```text
Fiscal Year = YEAR1
Journal Entry = JRNENTRY
JournalDate = TRXDATE, fallback PERIODDT
Reference = REFRENCE, fallback BUDGETID
Amount = BUDGETAMT + BudgerAdjustment
```

Group by fiscal year, JRNENTRY, and ACTINDX; round `sum(Amount)` to two decimals
and remove zero account totals.

An Amendment is a journal whose complete rounded account totals have a nonzero
net sum. Do not classify before collecting every source line.

| Target column | Transformation |
| --- | --- |
| `Ledger Type` / `TransactionType` | `Budget Amendment` |
| `Group ID` | `BAM-FY{YYYY}-{JRNENTRY}` |
| `External JE number` | `GP-BUDGET-{YYYY}-AMD-{JRNENTRY}` |
| `JournalDate` | Effective source date above |
| `Accounting String` | Approved account resolution |
| Debit / Credit | Positive Amount → debit; negative → absolute credit |
| `JE Description` | `FY {YYYY} budget amendment {Reference/JRNENTRY}` |
| `JE Line Description` | Account description; include legacy key in audit/exclusion output |

Balance each amendment with the approved offset account using the Adoption
residual rule. Exclude unapproved suspense rather than silently posting it.

## Budget Transfer mapping

Use the same unified transaction history and account aggregation as Amendment.
A Transfer is a journal whose complete rounded account totals sum to zero.

| Target column | Transformation |
| --- | --- |
| `Ledger Type` / `TransactionType` | `Budget Transfer` |
| `Group ID` | `BT-FY{YYYY}-{JRNENTRY}` |
| `External JE number` | `GP-BUDGET-{YYYY}-TRF-{JRNENTRY}` |
| `JournalDate` | Effective source date |
| `Accounting String` | Approved from/to account |
| Debit / Credit | Positive → debit/to; negative → absolute credit/from |
| `JE Description` | `FY {YYYY} budget transfer {Reference/JRNENTRY}` |
| `JE Line Description` | Account description |

No offset is permitted for a true transfer. Its source lines must balance after
rounding. A transfer requiring an offset is misclassified or incomplete.

Amendment and Transfer selection must be complementary: each `(FY,JRNENTRY)`
appears in exactly one class.

## Target Journal Entry columns

Use the complete destination template. Sarasota's budget file uses:

```text
Ledger Type,Group ID,External JE number,JE Line Number,TransactionType,JournalDate,Accounting String,DebitAmount,CreditAmount,Acquisition Cost,Acquisition Date,Asset Description,Asset ID,Bank Account,Benefit Type,Budget ID,Budget Name,Check Date,Check No,Contract ID,Customer ID,Customer Name,Date Paid,Depreciation Method,Depreciation Period,Disposal Date,Disposal Method,Earnings Code,Employee ID,Fee Label,Gain/Loss,Grant ID,Invoice Date,Invoice No,Pay Method,Payment Date,Payment ID,Payment Type,Payroll Disbursement,PO Number,Position Code,Processed By,Receipt Category,Receipt Category Description,Request ID,Requestor ID,Sale Amount,Tender Comment,Tender Type,Useful Life,Vendor ID,Vendor Name,Version,Organization Name,JE Description,JE Line Description
```

For budget imports, leave unrelated asset, AP, AR, payroll, receipt, vendor,
customer, payment, and procurement columns blank unless the current template
explicitly requires them.

## OpenGov validation gates

### Tier 1 — file, schema, and row format

- UTF-8 CSV; maximum 200 MB.
- Header spelling, case, and order match the current template.
- No empty data rows or internal audit columns.
- Group ID is present; required for asynchronous import.
- Required budget fields are populated.
- JournalDate is valid `M/D/YYYY` or `MM/DD/YYYY`.
- Amounts are numeric, nonnegative, and at most two decimals.
- Exactly one of DebitAmount/CreditAmount is positive per line.
- Group ID + JE Line Number is unique.
- Line numbers are positive and deterministic.
- Files over the destination synchronous limit use async; Sarasota guidance
  uses 500 rows.

### Tier 2 — cross-row and business rules

For every Group ID:

- total debit equals total credit; require exact cents when possible;
- all header values are identical across lines;
- one ledger type and one transaction type only;
- one fiscal year/effective date context;
- external number is stable and unique;
- source rows and output rows reconcile after documented exclusions;
- no account is duplicated due to source-union overlap.

Classification checks:

- Adoption amounts reconcile to approved annual GP totals.
- Amendment source journal net is nonzero before offset.
- Transfer source journal net is exactly zero and has no offset.
- No source JRNENTRY occurs in both Amendment and Transfer.
- No amendment/transfer exists without reliable source history.
- Adoption is not duplicated by later event history.

### Tier 3 — target-instance validations

- Organization unit exists or verified primary default applies.
- JE source is enabled.
- Ledger + source + transaction type is a valid JE type.
- JournalDate belongs to the intended fiscal year and an open period.
- Every accounting string exists, is active, and permits posting.
- Every detail and offset account has `budgetingAllowed=true`.
- Restricted net/system accounts are not used as ordinary detail lines.
- External JE number is not already imported.
- Async batch behavior and atomicity are understood before upload.

### Sequencing validations

- Segment codes and valid account combinations are loaded first.
- Budget Adoption is imported and verified before Amendment.
- Amendment is imported before Transfer when transfers rely on amended budget.
- After each stage, verify OpenGov budget inquiry before proceeding.

## Reconciliation

Produce controls by fiscal year, budget ID, Group ID, and account:

1. Source row count and raw amount.
2. Aggregated nonzero source lines and amount.
3. Exact/derived/unresolved account counts and amounts.
4. Excluded lines and amounts by reason.
5. Output detail count and amount before offset.
6. Offset amount and approved account.
7. Output debit, credit, and difference.
8. Imported OpenGov totals.

Final business equation:

```text
Revised Budget = Adopted Budget + Amendments + Transfers
```

Reconcile this equation by fiscal year and accounting string. Also compare
OpenGov totals to the approved GP budget report, not only to the extract.

## Mandatory outputs

- `budget_adoption.csv`
- `budget_amendment.csv` when reliable history exists
- `budget_transfer.csv` when reliable history exists
- Unmatched/account-mapping report
- Exclusions report with every reason and amount
- Validation report with check, count, PASS/FAIL, and sample keys
- Reconciliation report
- Target-readiness report with PASS/FAIL/UNVERIFIED
- Run manifest with source/template/crosswalk versions, parameters, hashes,
  counts, amounts, and import order

Header-only Amendment/Transfer files are acceptable evidence of no source
history, but they are not transactions to upload.

## Hard rules

1. Never invent headers, ledger values, or JE type combinations.
2. Never apply Sarasota's calendar, segment mapping, department exception,
   suspense, organization, or offset accounts to another customer by default.
3. Never treat all GP budget IDs as simultaneously active without business
   confirmation.
4. Never infer amendment/transfer events from final revised balances.
5. Never classify a transaction before reading all its lines.
6. Never put the same source journal in Amendment and Transfer.
7. Never use an offset for a Transfer.
8. Never use an offset to hide mapping or source errors.
9. Never upload unresolved or inactive accounts.
10. Never accept global balance when an individual Group ID is unbalanced.
11. Never import before target COA, JE types, org units, and periods are ready.
12. Current destination template and batch behavior override this skill;
    document observed differences before remapping.
