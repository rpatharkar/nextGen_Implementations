---
name: accufund-gl-to-opengov
description: Maps AccuFund chart-of-accounts and general-ledger transactions into OpenGov GL segment, valid-code-combination, crosswalk, fund-account, and Journal Entry import CSVs. Use when given AccuFund database extracts and asked to design GL mappings, generate journal imports, validate accounts and fiscal periods, or reconcile debits and credits.
---

# AccuFund GL to OpenGov

Portable mapping contract for AccuFund chart-of-accounts and journal data.

## Authority and hard rules

1. Download each current CSV template from the target OpenGov instance. Exact headers, configured segment names, enums, and target master data override this skill.
2. Do not invent accounts, segment codes, accounting strings, balancing lines, fiscal dates, or journal relationships.
3. Use UTF-8 CSV, exact case-sensitive headers, no empty rows, and no currency symbols/thousands separators.
4. Dates must be `M/D/YYYY` or `MM/DD/YYYY`, not ISO, unless the template says otherwise.
5. Use decimal arithmetic. Amounts are nonnegative with at most 2 decimals in the target debit/credit cells.
6. Every journal line has debit or credit, never both. Every journal group must balance.
7. Treat account strings and IDs as text; preserve separators and leading zeroes.
8. Never pass an unmapped legacy account through unless it is verified to exist as that exact accounting string in the target.

## Import order

```text
Segment Codes
→ Valid Code Combinations (COA Accounts)
→ optional Group Hierarchy / Fund Account Mapping / Crosswalk
→ Journal Entry
```

The target must also have organization units, JE sources, ledger types, transaction types, JE-type combinations, fiscal calendar, and open periods configured.

## AccuFund source model

Inspect schemas case-insensitively. Common sources:

| Source | Grain / key | Relevant data |
|---|---|---|
| `GLact` | One COA account, `ACCOUNTID` | `ACCOUNT`, `DESCRIPTION`, `STATUS`, `BALANCESHEET`, structure |
| `F9_TRX` | One ledger transaction line | `ACCOUNT`, segment fields, `SOURCE`, `ACTIVITYDATE`, `Period`, `OPENYEAR`, `BalanceType`, `POSTTYPE`, `DESCRIPTION`, `REF`, `ACCOUNTID`, signed `AMOUNT` |
| `GLtac` | One transaction/control, `TRANSACTIONID` | `JE`, date, source, activity/post type, reference, description, links to AP/AR/bank/assets |
| `GLacu` | Account usage | Links `ACCOUNTID` to bank/fund and other modules |
| `EXglp` | Optional posting batch | Posted date/journal/reference |
| `APinv`, `APbac`, `APbnk`, `ARinv`, `AFlst` | Subledger enrichment | Invoice, check, vendor, customer, bank context |
| COA crosswalk | Project-supplied lookup | Legacy `ACCOUNT` → exact OpenGov Accounting String |

Do not assume every AccuFund installation has `F9_TRX`; equivalent posted-detail tables are acceptable if they provide account, signed amount, date, and a stable journal grouping key.

## Discovery output required before mapping

Produce:

- Source table/column/type inventory and row counts.
- Null/duplicate profile for transaction IDs, account IDs, journal IDs, dates, and crosswalk keys.
- Distinct `BalanceType`, `SOURCE`, `ACTIVITYTYPE`, and `POSTTYPE` values with counts.
- Account format/segment analysis.
- Target lookups: segment display names, org units, enabled JE sources, ledger/transaction types, open periods, valid accounting strings.
- A documented journal-grain decision. Prefer a true JE identifier; use a natural key only after collision analysis.

## COA and segment mapping

### Segment Codes (`templateType=COA_SEGMENT`)

Exact common headers:

`Segment Display Name, Segment Code, Code Description, Account Type, Tags, default Parent, Organization Name`

| Target | AccuFund mapping | Validation |
|---|---|---|
| `Segment Display Name` | Target-configured dimension name for each parsed account segment | Required; exact target name |
| `Segment Code` | Distinct normalized component from `GLact.ACCOUNT` | Required; uppercase; normally `^[A-Z0-9_-]+$`; preserve padding |
| `Code Description` | Segment master description if available; otherwise approved account-derived lookup | Required, ≤255 |
| `Account Type` | Object classification crosswalk | Required for Object segment; target enum |
| `Tags` | Approved metadata, semicolon-separated | Optional, ≤500 |
| `default Parent` | Approved target group | Must exist and belong to segment |
| `Organization Name` | Exact target org or blank for primary | Target-resolvable |

Do not derive a segment's description by choosing an arbitrary full-account description when the same code has conflicting descriptions. Report conflicts.

### Valid Code Combinations (`templateType=COA_ACCOUNTS`)

Fixed common headers:

`Description, Tags, SegmentAll, Budgeting Allowed, Posting Allowed, Modules Allowed, Valid From, Valid to`

The remaining columns are dynamic: one exact target Segment Display Name per segment.

| Target | Mapping | Validation |
|---|---|---|
| `Description` | `GLact.DESCRIPTION` or approved canonical description | Required, 1–255 |
| `Tags` | Approved semicolon-separated tags | Optional |
| `SegmentAll` | Leave blank unless target template defines use | Do not guess |
| `Budgeting Allowed` | Policy/account-class crosswalk | Boolean |
| `Posting Allowed` | Active posting account policy; do not infer solely from source status | Boolean |
| `Modules Allowed` | Approved enabled source labels such as `GL;AP;AR` | At least one where required |
| `Valid From` | Approved effective date/migration start | Required date |
| `Valid to` | Source close date if reliable | Blank or after Valid From |
| Dynamic segment columns | Parsed legacy components mapped to target codes | Required segments populated; each code exists |

Reject duplicate combinations and overlapping validity ranges. Every component must already exist as a Segment Code.

### Crosswalk (`templateType=CROSSWALK_MAPPING`)

Headers:

`Segment Display Name, External Code, External Code Description, OpenGov Code, OpenGov Code Description`

Use this only for segment-level external-code mapping. Each `OpenGov Code` must exist for the named segment. Maintain a separate full-account crosswalk when legacy and target accounting strings cannot be derived segment-by-segment.

### Group Hierarchy and Fund Account Mapping

Only map when source or an approved design supplies these relationships.

Group headers:

`Parent, Child, Type, Purpose, Segment Display Name, Tags, Display Name On Report, Group Code, Description, Default Parent, Organization Name`

Validate parent/child existence, segment ownership, node type, no cycles, and target organization.

Fund mapping headers:

`Fund Code, Change in Fund Balance, Fund Balance Account, Accounts Payable Account, Retainage Payable Account, Payment Discount Account, Reserve For Encumbrances Account, Reserve For Pre-Encumbrances Account, Cash Account, BnP Controlling Account`

`Fund Code` must exist. Every populated account must be an exact target accounting string in the same fund and have the required system-account classification. Do not infer system accounts solely from account-number patterns.

## Journal source filtering

Define conversion scope explicitly:

- Actuals commonly use `F9_TRX.BalanceType='Actual'`.
- Budget values require a separately approved scope and ledger strategy; do not mix them into Actuals.
- Set inclusive start/end dates from migration requirements; never use `CURRENT_DATE` in a repeatable historical mapping without recording the resolved cutoff.
- Decide whether to include posted only, voided/reversed, period 13–15, and subledger-generated entries.
- Avoid double loading: if AP invoices/payments are imported with GL impact, agree whether related `SOURCE='A/P'` journal rows are excluded from GL history.

## Budget journal data

OpenGov loads budget history through `JOURNAL_ENTRY`, normally in this order:

```text
Budget Adoption → Budget Amendment → Budget Transfer
```

Use authoritative AccuFund annual-budget summary/balance tables (commonly `F9_SUM`, `GLacs`, or the installation's budget-detail tables) for adopted/revised totals. `F9_TRX` budget rows may be used only after they reconcile to those authoritative totals; transaction detail can be incomplete for annual budgets.

| Budget class | Ledger Type | TransactionType | Source rule |
|---|---|---|---|
| Original/opening budget | `Budget Adoption` | `Budget Adoption` or approved `Manual` | Original budget amount by account/fiscal year |
| Approved increase/decrease | `Budget Amendment` | `Budget Amendment` or approved `Manual` | Amendment documents/transactions only |
| Move between accounts | `Budget Transfer` | `Budget Transfer` or approved `Manual` | Paired from/to transfer detail |

If AccuFund supplies only a final revised amount with no trustworthy history, obtain business approval before treating it as Adoption. Do not manufacture Amendment or Transfer history.

Budget lines follow the same debit-XOR-credit and group-balance rules. Confirm the entity's revenue/expense sign convention and `budgetingAllowed=true` on every target account. An approved B&P controlling/offset account may balance an adoption or amendment only when target configuration and migration design explicitly require it; never derive that account from a number pattern.

## Journal grain and grouping

Best grouping key, in order:

1. A true source fiscal year + JE number/transaction control ID from `GLtac`.
2. A proven link from detail to `GLtac`.
3. A natural key such as `(activity date, description, source, reference)` only after measuring collisions.

Do not group solely by `(date, description)` without reporting collisions; unrelated entries can merge.

Create a stable `Group ID`, e.g. `{fiscal-year}-{source-je-id}`. All header fields must be identical within a Group ID.

## Amount mapping

AccuFund `F9_TRX.AMOUNT` convention used by this project:

```text
amount > 0  → DebitAmount = round(amount, 2), CreditAmount = blank/0
amount < 0  → DebitAmount = blank/0, CreditAmount = round(abs(amount), 2)
amount = 0  → omit unless a documented nonfinancial line is required
```

If source metadata proves the opposite convention, use that convention and document evidence.

When aggregating:

- Group by Group ID and mapped Accounting String.
- Sum positive and negative source amounts separately; do not net them.
- If both sides remain for one account, emit two target rows so debit XOR credit holds.
- Drop a side only when its rounded absolute value is below the approved threshold.
- Never add a balancing line merely to force equality. Investigate missing accounts, rounding, scope, or grouping.

## Journal Entry target fields

The repository template has these fields; the downloaded target template wins.

### Core fields

| Target column | AccuFund mapping | Validation |
|---|---|---|
| `Ledger Type` | `Actual→Actuals`; `Budget→approved budget ledger`; `Enc→Encumbrance`; otherwise crosswalk | Required/exact target display |
| `Group ID` | Stable source journal key | Required for async; groups one JE |
| `External JE number` | `GLtac.JE` or external posting journal when reliable | Unique if populated |
| `JE Line Number` | Deterministic sequence within Group ID | Positive, unique, contiguous preferred |
| `TransactionType` | Target-approved type; commonly `Manual` for converted GL | Ledger+source+type combination exists |
| `JournalDate` | `F9_TRX.ACTIVITYDATE` or control date | Valid format; open target period |
| `Accounting String` | Full-account crosswalk of `F9_TRX.ACCOUNT` | Required; exists, active, posting allowed |
| `DebitAmount` | Positive source side | Nonnegative, 2 decimals, XOR |
| `CreditAmount` | Absolute negative source side | Nonnegative, 2 decimals, XOR |

### Optional enrichment fields

Map only when the linked source record belongs unambiguously to the journal. Blank is safer than an incorrect value.

| Target column | AccuFund source / rule |
|---|---|
| `Acquisition Cost` | Asset acquisition amount when linked and target accepts it |
| `Acquisition Date` | Linked asset acquisition date; target date format |
| `Asset Description` | Linked asset description |
| `Asset ID` | Linked asset external/target ID, not an unverified internal surrogate |
| `Bank Account` | `APbnk.BANK`/`DESCRIPTION` or target-resolved bank account name |
| `Benefit Type` | Payroll/benefit source only |
| `Budget ID` | Target-resolved budget ID only |
| `Budget Name` | Target-resolved budget name |
| `Check Date` | `APpay.CHECKDATE` or linked `APbac.ACTIVITYDATE` |
| `Check No` | Linked check reference; keep as text |
| `Contract ID` | Target-resolved contract |
| `Customer ID` | Linked `ARinv.LISTID` or approved external code |
| `Customer Name` | Linked customer `AFlst.NAME` |
| `Date Paid` | Linked payment/check date |
| `Depreciation Method` | Linked asset master value |
| `Depreciation Period` | Linked asset master value |
| `Disposal Date` | Linked disposal date |
| `Disposal Method` | Linked disposal method |
| `Earnings Code` | Payroll source only |
| `Employee ID` | Payroll source employee external code |
| `Fee Label` | Tax/fee source only |
| `Gain/Loss` | Linked asset disposal amount/classification |
| `Grant ID` | Target-resolved grant |
| `Invoice Date` | Linked `APinv.INVOICEDATE` |
| `Invoice No` | Linked `APinv.INVOICE`; do not substitute unrelated `REF` |
| `Pay Method` | `CHECK`, `ACH`, etc. only when source proves method |
| `Payment Date` | Linked payment/check date |
| `Payment ID` | Stable external payment reference or resolved target ID |
| `Payment Type` | Target enum from linked payment |
| `Payroll Disbursement` | Payroll source only |
| `PO Number` | Linked PO number |
| `Position Code` | Payroll source only |
| `Processed By` | `GLtac.CREATEID` only if target accepts that external value; otherwise crosswalk |
| `Receipt Category` | AR/receipt source only |
| `Receipt Category Description` | AR/receipt source only |
| `Request ID` | Linked requisition/request |
| `Requestor ID` | Target-resolved requestor |
| `Sale Amount` | Asset sale/disposal source only |
| `Tender Comment` | Linked cash-receipt tender comment |
| `Tender Type` | Target-resolved tender type |
| `Useful Life` | Linked asset useful life |
| `Vendor ID` | Linked `APinv/APbac.LISTID` only if target accepts external code; otherwise resolved target ID |
| `Vendor Name` | Linked vendor `AFlst.NAME` |
| `Version` | Blank unless current template defines semantics |
| `Organization Unit` | Exact target org name; blank only when primary-org default is confirmed |
| `JE Description` | Clean control/detail description; one consistent value per group |
| `JE Line Description` | Best line-level description; preserve useful detail |

Use exact downloaded spelling. Older templates may contain different fields or typos; never merge two template versions.

## Subledger enrichment

Use `GLtac` link columns, not fuzzy names:

- AP: `APINVOICEID` → `APinv` → vendor `AFlst`.
- Check/bank: `BANKACTIVITYID` → `APbac`/`APpay`/`APbnk`.
- AR: `ARACTIVITYID`, `ARPAYID`, or `ARRECEIPTID` → corresponding AR tables.
- Other modules: use the explicit activity ID for that module.

If only a reference is available, require uniqueness within source/date/module before enriching. Do not broadcast the maximum nonblank value across a group when conflicting values exist; report conflicts and either split the journal or leave the optional field blank.

## Validation gates

### File and row

- Exact template headers; required columns present.
- Valid dates and decimals; no `NULL`/`N/A` literals.
- Every line has one positive side only.
- Accounting String resolves and is valid on JournalDate.
- Segment/org/fund ownership and enabled module rules pass.

### Group

- Group ID is stable and no source journals were accidentally merged.
- Ledger Type, TransactionType, JournalDate, source, org, external JE number, and JE description are consistent.
- Sum debits = sum credits exactly at 2 decimals; report pre-round and post-round differences.
- External JE number is unique when populated.
- Fiscal period is open; special periods are explicitly approved.

### COA and crosswalk

- Every in-scope source account has exactly one active target mapping.
- No source account maps to multiple targets without effective-date logic.
- Many-to-one mappings are reported and approved.
- All target accounts exist and permit the selected JE source and posting date.

### Reconciliation

Reconcile by source fiscal year, period, source module, and journal:

```text
source row count → transformed sides → output row count
source signed total = 0 per source journal (or documented exception)
output debit total = output credit total per Group ID
source debit total = output debit total
source credit total = output credit total
unmapped/excluded totals are listed, never hidden
```

Also compare account-level and period-level net activity before and after crosswalk. Many-to-one target accounts must reconcile to the sum of their legacy accounts.

## Required deliverables

1. Populated OpenGov CSV files in dependency order.
2. Field mapping manifest with source, target, transformation, lookup, requirement, validation, and assumption.
3. COA crosswalk with effective dates/status where applicable.
4. Validation and reconciliation report with PASS/FAIL, counts, debit/credit totals, collisions, unmapped accounts, closed-period rows, and excluded modules.
5. Rejection file keyed back to source rows.

Do not declare upload-ready until all required lookups, account mappings, group balances, date rules, and reconciliations pass.
