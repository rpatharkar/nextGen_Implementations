---
name: microsoft-dynamics-gp-gl-mapping
description: >-
  Maps Microsoft Dynamics GP General Ledger extracts to OpenGov NextGen GL
  journal-entry imports, including historical actuals, opening balances, budget
  adoption, amendments, and transfers. Use when converting GP GL tables, CSVs,
  Parquet files, or SQL extracts into OpenGov GL import files and validating
  accounting strings, fiscal periods, journal balance, and import readiness.
---

# Microsoft Dynamics GP GL Mapping

## Purpose

Use this skill to transform Microsoft Dynamics GP (Great Plains) GL data into
OpenGov NextGen GL Journal Entry import CSVs outside the Sarasota repository.
The user may provide files rather than database tables; identify files by their
GP table names and required columns.

This skill covers:

1. Historical actual journal entries
2. Opening balances
3. Budget adoption
4. Budget amendments
5. Budget transfers
6. COA resolution and optional document-context enrichment
7. Pre-import validation, reconciliation, exclusions, and target readiness

It maps to the OpenGov **Journal Entry import schema**, not directly to an
internal OpenGov database. Never invent internal IDs or import headers.

## Authority and template drift

Always download the current Journal Entry template from the destination
OpenGov instance. Its exact headers and instructions override this skill.

Sarasota artifacts contain two template generations:

- Current actual/opening-balance outputs use `Organization Unit`.
- Older budget outputs use `Organization Name`.

Never combine headers from different template generations. Rename only after
confirming the destination template. Preserve exact spelling, case, order, and
even official typos.

Do not mark a file upload-ready while a hard validation is failed or a required
target lookup is unverified.

## Required source package

### Core GP GL tables

| GP table | Required purpose and columns |
| --- | --- |
| `GL20000` | Open-year posted GL distributions: `JRNENTRY`, `RCTRXSEQ`, `TRXDATE`, `DOCDATE`, `ACTINDX`, `DEBITAMT`, `CRDTAMNT`, `SOURCDOC`, `TRXSORCE`, `REFRENCE`, `DSCRIPTN`, `DEX_ROW_ID`; optional document fields |
| `GL30000` | Historical posted GL distributions with the same logical columns |
| `GL00100` | Account master: `ACTINDX`, account segments, `ACTDESCR`, `ACCTTYPE`, active/posting attributes if available |
| `GL00105` | Account index to formatted legacy string: `ACTINDX`, `ACTNUMST` |
| `GL10111` | Account-period history and opening balance: `YEAR1`, `PERIODID`, `ACTINDX`, `PERDBLNC`, debit/credit activity |
| `GL00200` | Budget master: `YEAR1`, `BUDGETID`, `BUDCOMNT`, `From_Date`, `TODATE` |
| `GL00201` | Budget detail: `YEAR1`, `BUDGETID`, `PERIODID`, `PERIODDT`, `ACTINDX`, `ACTNUMBR_1..3`, `BUDGETAMT` |

### Budget-history tables

Request `GL12000`, `GL12001`, and `GL32000`. Use them only after confirming
their roles and grains in the supplied GP company:

- open/posted budget journal controls and lines;
- amendment or transfer identity;
- dates, source documents, descriptions, and debit/credit direction.

If these tables contain no reliable history, do not invent amendments or
transfers. Load final revised balances as Budget Adoption only after written
business approval.

### Optional enrichment tables

| GP table | Use |
| --- | --- |
| `PM30200`, `PM20000` | AP invoice/payment number, dates, PO, payment method, vendor context |
| `PM00200` | Vendor name lookup |
| `RM20101` | AR customer invoice/check context |
| `CM20200` | Check clearing date |

Enrichment is optional. It must never change accounting amount, account,
journal identity, or date. Leave unsupported optional target fields blank.

### Destination-specific references

Require current exports or approved lookups for:

- OpenGov accounting strings and their active/effective dates
- `postingAllowed`, `budgetingAllowed`, and restricted/system-account flags
- Organization-unit names and the primary organization unit
- Fiscal years, periods, and open/closed status
- Enabled JE sources
- Valid `(Ledger Type, JE Source, TransactionType)` combinations
- Existing External JE numbers and Group IDs, if exposed
- Approved opening-balance and budget offset accounts

## Parameters that must not be hard-coded

Capture these in the run manifest:

- GP company/database
- Source extraction timestamp
- First and last fiscal year/date
- Fiscal-year start month and day
- OpenGov entity
- Organization unit
- Target template version/date
- JE source and transaction-type choices
- Balance tolerance
- Approved suspense account, if any
- Approved opening/budget offset accounts

Sarasota uses an October 1–September 30 fiscal year:

```text
fiscal_year = year(date) + 1 when month(date) >= 10, otherwise year(date)
```

That rule is not universal. Derive fiscal year from the customer's configured
calendar and verify it against GP periods.

## Global normalization

- Read identifiers as text; preserve leading zeros.
- Trim join keys, descriptions, account segments, and source codes.
- Convert GP sentinel dates such as `1900-01-01` to null.
- Use a valid `DOCDATE`; otherwise use `TRXDATE` when the documented profile
  allows it.
- Output dates in the exact template format, normally `M/D/YYYY` or
  `MM/DD/YYYY`.
- Round monetary output to two decimals using decimal arithmetic.
- Remove currency symbols and thousands separators.
- Convert null placeholders (`NULL`, `N/A`, `#N/A`, `-`) to blank.
- Keep debit and credit as nonnegative magnitudes.
- If a source amount is negative, move its absolute value to the opposite side
  only when the GP accounting meaning has been verified.
- Remove empty rows and normally remove zero-debit/zero-credit lines.
- Make sorting deterministic before assigning line numbers.

## COA mapping

### Legacy account construction

Preferred source:

```text
GL00105.ACTNUMST joined by ACTINDX
```

Fallback when `ACTNUMST` is unavailable:

```text
trim(GL00100.ACTNUMBR_1) + "-" +
trim(GL00100.ACTNUMBR_2) + "-" +
trim(GL00100.ACTNUMBR_3)
```

For Sarasota, the legacy pattern is `#####-##-###` and the OpenGov pattern is
`###-###-###-#####-######`. Treat these as customer-specific profiles, not
universal GP or OpenGov formats.

### Resolution order

1. **EXACT** — exact approved legacy-account → OpenGov-account crosswalk.
2. **DERIVED** — construct from independently approved segment crosswalks only.
3. **UNRESOLVED** — exclude and report.

Sarasota's approved derived profile is:

```text
OpenGov = Fund + "-" + Department + "-" + Program + "-" + Object + "-" + Project
Fund    = "100"
Project = "000000"
```

The object, department, and program values come from separate approved
crosswalks. Sarasota also has a specific legacy department `14 → 210`
exception. Do not apply that exception to another customer.

Validate crosswalks before use:

- one legacy account maps to at most one OpenGov account;
- target account format is valid;
- target account exists and is active for the journal date;
- no duplicate or contradictory segment mappings;
- every derived combination exists in OpenGov;
- account type and normal balance remain logically compatible;
- mapping method and crosswalk version are retained in audit output.

The Sarasota actuals process used `100-888-888-88888-000000` for unresolved
accounts. This is not a portable default. Use suspense only when that exact
account exists, accepts posting, and the customer approves every routed amount.
Otherwise exclude unresolved rows.

## Current Journal Entry target columns

The Sarasota current template has these columns in order:

```text
Ledger Type,Group ID,External JE number,JE Line Number,TransactionType,JournalDate,Accounting String,DebitAmount,CreditAmount,Acquisition Cost,Acquisition Date,Asset Description,Asset ID,Bank Account,Benefit Type,Budget ID,Budget Name,Check Date,Check No,Contract ID,Customer ID,Customer Name,Date Paid,Depreciation Method,Depreciation Period,Disposal Date,Disposal Method,Earnings Code,Employee ID,Fee Label,Gain/Loss,Grant ID,Invoice Date,Invoice No,Pay Method,Payment Date,Payment ID,Payment Type,Payroll Disbursement,PO Number,Position Code,Processed By,Receipt Category,Receipt Category Description,Request ID,Requestor ID,Sale Amount,Tender Comment,Tender Type,Useful Life,Vendor ID,Vendor Name,Version,Organization Unit,JE Description,JE Line Description
```

If the downloaded target template differs, use it instead.

## Historical actual journal entries

### Source selection and deduplication

1. Union `GL20000` with source priority 1 and `GL30000` with priority 2.
2. Derive the fiscal year from the validated journal date.
3. For the same native journal identity, prefer `GL20000` over `GL30000`.
4. Preserve line order using `RCTRXSEQ`, then `DEX_ROW_ID`.
5. Exclude GP year-close `SOURCDOC` values `BBF` and `P/L` when a separate
   opening-balance JE is loaded. Report their counts and amounts.
6. Exclude unposted work tables unless the migration scope explicitly includes
   unposted journals.

Use `(company, fiscal year, JRNENTRY)` as the preferred native journal key.
Sarasota's final mapped files grouped rows by `JournalDate + JE Description`
and used the minimum `JRNENTRY` as the external number. That may merge distinct
GP journals sharing a date and description. Reuse it only after proving native
journals do not balance independently or the merge was intentionally approved.

### Actuals target mapping

| Target column | GP source / transformation | Rule |
| --- | --- | --- |
| `Ledger Type` | Sarasota literal `Actuals` | Must be an accepted target value |
| `Group ID` | Preferred `FY-JRNENTRY`; include company when numbers can collide | Required and stable; one balanced JE |
| `External JE number` | Text `JRNENTRY` or approved unique source key | Must not duplicate an existing import |
| `JE Line Number` | `row_number` by source sequence/row ID | Positive; unique within Group ID |
| `TransactionType` | Sarasota final files use `Manual`; older logic used `TRXSORCE` | Must form a valid target JE type |
| `JournalDate` | Valid `DOCDATE`, else `TRXDATE`; Sarasota final files use `TRXDATE` | Valid date in intended fiscal period |
| `Accounting String` | Resolve `ACTINDX` through legacy account and crosswalk | Required; exact active target account |
| `DebitAmount` | Rounded `DEBITAMT` | Nonnegative; debit XOR credit |
| `CreditAmount` | Rounded `CRDTAMNT` | Nonnegative; debit XOR credit |
| Organization column | Exact target org-unit name or blank for verified primary | Same for every row in group |
| `JE Description` | Header `DSCRIPTN`, fallback `REFRENCE`; trim | Sarasota caps at 200 |
| `JE Line Description` | Line `DSCRIPTN`, fallback `ACTDESCR` | Include legacy key for approved derived/suspense audit |

Header-level fields must be identical on all rows in a Group ID.

### Optional context mapping

Populate only when a deterministic source relationship exists:

| Target fields | Source logic |
| --- | --- |
| `Vendor ID`, `Vendor Name` | For non-AR/non-payroll series, `ORMSTRID/ORMSTRNM`; vendor name fallback from `PM00200` |
| `Customer ID`, `Customer Name` | `ORMSTRID/ORMSTRNM` for GP receivables series |
| `Invoice No`, `Invoice Date` | Match AP by vendor + `ORDOCNUM`, then voucher/reference; else match AR by customer + document |
| `Payment ID` | AP `VCHRNMBR` for matched payment/voucher |
| `Payment Type` | GP payment `PYENTTYP=3 → ACH`; other payment → `CHECK` |
| `Pay Method` | `PYMTRMID`, fallback approved CHECK/ACH derivation |
| `Payment Date`, `Date Paid` | Matched payment date/due date according to approved profile |
| `Check No` | `ORCTRNUM`, matched payment document, or AR check number |
| `Check Date` | `CM20200` cleared date, fallback payment date only when approved |
| `PO Number` | AP `PORDNMBR`; limited source-document fallback for purchasing series |

If context found on one line is propagated to sibling lines, first prove the
entire JE relates to one document. Do not propagate conflicting invoice,
vendor, customer, payment, check, or PO values.

All remaining optional template columns stay blank unless authoritative source
lineage and target validation rules are documented.

## Opening-balance mapping

Opening balances are a separate `Actuals` journal and must not be duplicated by
GP `BBF` or `P/L` closing entries.

### Source and filters

For target fiscal year `FY`:

1. Read `GL10111` where `YEAR1 = FY` and `PERIODID = 0`.
2. Join `GL00105` and `GL00100` by `ACTINDX`.
3. Keep posting accounts only (`GL00100.ACCTTYPE = 1` in Sarasota).
4. Drop balances that round to zero.
5. Map `PERDBLNC >= 0` to debit; map negative `PERDBLNC` to positive credit.
6. Set JournalDate to the day before the fiscal-year start.

Confirm that `PERIODID=0/PERDBLNC` is the correct beginning-balance convention
for the supplied GP company. If unavailable, derive opening balances only from
an approved prior-year trial balance; never guess from current activity.

### Opening target mapping

| Target column | Transformation |
| --- | --- |
| `Ledger Type` | `Actuals` |
| `Group ID` | Stable value such as `FY-OPENING`; split by fund if required |
| `External JE number` | Stable unique value such as `OPENING-FY` |
| `JE Line Number` | Deterministic positive sequence |
| `TransactionType` | `Manual`, if valid in target |
| `JournalDate` | Day before FY start |
| `Accounting String` | Approved exact/derived crosswalk |
| `DebitAmount` / `CreditAmount` | Sign rule above |
| Organization column | Exact target org or verified blank-primary behavior |
| `JE Description` | `Opening Balance FY####` |
| `JE Line Description` | `ACTDESCR`; include legacy account and mapping method for non-exact mapping |

### Opening-balance hard validations

- Source has at least one eligible line.
- Every source `ACTINDX` resolves to one legacy account.
- Every exported line resolves to an approved active OpenGov account.
- Debit equals credit for the complete opening JE within `0.01`.
- Debit equals credit by fund within `0.01` when fund-balanced accounting is
  required.
- No account has both debit and credit on one row.
- No duplicate `(Group ID, JE Line Number)` exists.
- Source net and output net agree after documented exclusions.
- Source opening trial balance agrees with GP's audited trial balance.
- Target opening balances after import agree by account and fund.
- Opening + imported activity reproduces each period-end GP trial balance.
- No BBF/P&L activity was also imported for the same opening.

Sarasota's FY2022 opening profile uses `YEAR1=2022`, `PERIODID=0`, and
JournalDate `09/30/2021`.

## Budget mapping

Budgets use the Journal Entry import; load Adoption before Amendment before
Transfer. Confirm separately whether opening balances or actuals load first.

### Source classification

Profile `GL00200`, `GL00201`, `GL12000`, `GL12001`, and `GL32000`.

- Original/final balance without history → approved `Budget Adoption`
- Budget journal with nonzero net change → `Budget Amendment`
- Budget journal with net zero across accounts → `Budget Transfer`

Sarasota had one active budget ID per FY and empty budget-history tables, so
FY2022–FY2026 final revised balances became Adoption; no activity was invented.

### Adoption

1. Sum `GL00201.BUDGETAMT` by FY and legacy account across periods; round and
   drop zero annual totals.
2. Use `GL00200.From_Date` as JournalDate and one Group ID per FY.
3. Export exact COA matches only; report derived/suspense/unmatched accounts.
4. Positive amount → debit; negative amount → positive credit.
5. Post the post-exclusion residual on the short side to an approved offset.

Sarasota's offset maps GP `10400-00-000`; never reuse it without approval.

### Amendment and transfer history

Union posted `GL32000` with open `GL12001` lines joined to `GL12000` on
`JRNENTRY+BACHNUMB`. For each row:

- FY = `YEAR1`
- JournalDate = `TRXDATE`, fallback `PERIODDT`
- Description = `REFRENCE`, fallback `BUDGETID`
- Amount = `BUDGETAMT + BudgerAdjustment`

Sum and round Amount by `FY + JRNENTRY + ACTINDX`; drop zero account totals.
Classify on the rounded sum across the complete journal:

- zero → Transfer, `Group ID = BT-FY{FY}-{JRNENTRY}`, no offset;
- nonzero → Amendment, `Group ID = BAM-FY{FY}-{JRNENTRY}`, balance with the
  approved offset account.

Positive amount is debit/to-account; negative amount is positive credit/from-
account. Resolve accounts using the approved COA policy and exclude unapproved
suspense. Classification must be complementary so no JRNENTRY enters both files.

### Target values

| Target | Adoption | Amendment | Transfer |
| --- | --- | --- | --- |
| `Ledger Type` / `TransactionType` | `Budget Adoption` | `Budget Amendment` | `Budget Transfer` |
| External number | Unique FY adoption key | Source `JRNENTRY` key | Source `JRNENTRY` key |
| JournalDate | `From_Date` | Effective source date | Effective source date |
| Amounts | Signed budget + offset | Signed change + offset | Signed to/from lines |
| Description | FY/budget narrative | Reference/budget ID | Reference/budget ID |

Populate Budget ID/Name and organization only when the current template expects
them. Every group must balance; every account must have `budgetingAllowed=true`;
never mix ledger types within a Group ID.

## Validation gates

### Gate 0 — File and template

- UTF-8 CSV with the current exact header and column order
- No mixed `Organization Unit`/`Organization Name` schema
- No extra internal/audit columns in import output
- No blank data rows, formulas, currency symbols, or comma-formatted amounts
- File at most 200 MB
- Use synchronous import only at or below the instance's row limit; Sarasota
  guidance uses 500 rows. Larger files use async and require Group ID.

### Gate 1 — Required row values

- Group ID, ledger type, transaction type, journal date, accounting string,
  line number, and required organization/source values are populated
- Exactly one of DebitAmount or CreditAmount is positive
- Amounts are nonnegative with at most two decimals
- Group ID + JE Line Number is unique
- No zero/zero rows unless explicitly accepted
- Dates parse in the target format
- Text values fit current template limits

### Gate 2 — Journal integrity

For each Group ID:

- debit total equals credit total; require exact cents when possible and never
  exceed `0.01` tolerance;
- at least two lines unless target-supported automatic balancing is approved;
- header fields are identical on every row;
- external number and native source relationship are deterministic;
- source line count and output line count reconcile after exclusions;
- no duplicate source distribution was loaded from open and history tables.

Also reconcile debit and credit by fiscal year, journal date, and fund. A global
grand-total balance does not prove individual journals are valid.

### Gate 3 — Dates and fiscal periods

- JournalDate maps to the intended GP fiscal year and period
- JournalDate is in an OpenGov fiscal period
- Period is open for import/posting
- Opening date is immediately before the target FY start
- Budget effective dates are in the intended budget year
- Sentinel, null, and future dates are excluded or reviewed
- Additional GP periods 13–15 are mapped only with an approved OpenGov policy

### Gate 4 — Target master data

- Organization unit exists; blank is used only when primary-default behavior is
  confirmed
- JE source is enabled
- `(Ledger Type, JE Source, TransactionType)` is configured
- Accounting string exists, is active/effective, and permits posting
- Budget accounts and offsets have `budgetingAllowed=true`
- Restricted net/system accounts are not used as ordinary lines
- Optional vendor/customer/bank/project/contract/grant values resolve when sent
- External JE number is unique or safely idempotent

These checks require destination-instance data and cannot be proven from GP
files alone.

### Gate 5 — Reconciliation

Create PASS/FAIL controls for:

1. GP source rows, journals, debit, and credit by fiscal year.
2. Open-vs-history deduplication counts and amounts.
3. Excluded BBF/P&L, zero, invalid-date, nonposting, and unresolved-account
   counts and amounts.
4. Exact, derived, suspense, and unresolved mapping coverage.
5. Output rows, groups, debit, and credit by fiscal year/date/fund.
6. Opening balances by legacy and OpenGov account.
7. Opening + activity = period-end trial balance by account and fund.
8. Budget source totals, excluded totals, detail totals, offset, and balanced
   output by fiscal year.
9. After import, OpenGov actual, opening, adopted, amended, transferred, and
   revised balances versus the approved GP control reports.

## Required deliverables

For each run produce:

- Upload-ready actual and opening-balance JE CSVs
- Budget Adoption/Amendment/Transfer CSVs when source evidence exists
- Account-mapping audit with legacy account, OpenGov account, method, and status
- Exclusions file with source key, amount, and every reason
- Validation report with check ID, error count, PASS/FAIL, and sample keys
- Reconciliation report with source/export/target totals
- Target-readiness report with PASS/FAIL/UNVERIFIED
- Run manifest with parameters, hashes, template version, counts, and totals

## Hard rules

1. Never use an old template when a current instance template is available.
2. Never hard-code Sarasota's fiscal calendar, organization, account shape,
   department exception, suspense, or offset accounts for another customer.
3. Never load an unresolved account silently.
4. Never merge native GP journals only to force balance.
5. Never add an unexplained balancing line.
6. Never import BBF/P&L closing artifacts together with the same opening
   balances.
7. Never invent budget amendment or transfer history from final balances.
8. Never accept a globally balanced file containing unbalanced Group IDs.
9. Never populate optional context from a weak or conflicting join.
10. Never upload before COA, JE-type, org-unit, and fiscal readiness is verified.
11. Preserve every exclusion and default as auditable evidence.
12. Current OpenGov template/batch behavior wins over this skill; document differences.
