---
name: incode9-general-ledger-mapping
description: Maps Incode9 general-ledger CSV extracts to OpenGov NextGen GL Segment Codes, Valid Code Combinations, Crosswalk Mapping, and Journal Entry imports. Use when GLCNTLF, GLHCNTLF, GLDETLF, GLHDETLF, GLBUDGF, GLHBUDGF, or an Incode9 COA crosswalk is supplied.
---

# Incode9 General Ledger mapping

Convert Incode9 chart-of-accounts and transaction extracts into OpenGov NextGen GL CSV templates. Use target-instance master data and preserve traceable source keys.

## Required inputs

1. Current accounts: `GLCNTLF.csv`; historical accounts: `GLHCNTLF.csv`.
2. Current activity: `GLDETLF.csv`; historical activity: `GLHDETLF.csv`.
3. Approved COA crosswalk containing legacy `OLD` account key and target `NEW` accounting string. If available, include target `ACCOUNT_PSEUDO_KEY` for reconciliation only.
4. Current target templates, segment definitions, organization units, enabled JE sources/type combinations, fiscal calendar/open periods, and COA export.
5. Optional `APMASTF.csv` for vendor-name enrichment.
6. For budget conversion, `GLBUDGF.csv` and `GLHBUDGF.csv`; apply the target's separately approved budget-JE policy.

The established legacy account key is `rtrim(company) + '-' + rtrim(control)`. A target accounting string cannot be derived safely from this key without the approved crosswalk or a confirmed target segment design.

The legacy bronze SQL loaded every source with `SELECT *` and therefore is not a complete source schema. Inventory the supplied CSV headers/types before mapping; missing referenced fields are blockers, and similarly named fields must not be substituted without confirming their meaning.

## Source branches and keys

Normalize current and history to common names:

| Logical field | Current source | Historical source |
|---|---|---|
| company | `gld_comp` | `glhd_comp` |
| control/account | `gld_cntl` | `glhd_cntl` |
| source fiscal year | max `glhd_yr` + 1 | `glhd_yr` |
| date code | `gld_date` | `glhd_date` |
| post-date code | `gld_post` | `glhd_post` |
| sequence | `gld_padd` | `glhd_padd` |
| transaction | `gld_tran` | `glhd_tran` |
| journal no. | `gld_jno` | `glhd_jno` |
| packet | `gld_packet` | `glhd_packet` |
| journal/source | `gld_journ` | `glhd_journ` |
| reference | `gld_ref` | `glhd_ref` |
| description | `gld_desc` | `glhd_desc` |
| signed amount | `gld_amt` | `glhd_amt` |
| AP/invoice/PO metadata | `gld_ap_type`, `gld_inv`, `gld_po` | `glhd_ap_type`, `glhd_inv`, `glhd_po` |
| vendor keys | `gld_vco`, `gld_vend` | `glhd_vco`, `glhd_vend` |
| encumbrance | `gld_enc` | `glhd_enc` |
| transaction type/note/project | `gld_ttype`, `gld_jnote`, `gld_proj`, `gld_pline` | historical equivalents |
| row identity | `A4GLIdentity` | `A4GLIdentity` |

Join current details to `GLCNTLF` on company + control. Join history to `GLHCNTLF` on company + control + year. Deduplicate native source rows before the union.

## Date conversion

Incode stores a date code as `period * 100 + day`.

1. `period = integer(date_code / 100)`.
2. `day = date_code % 100`.
3. For periods 1–12, convert using the engagement's confirmed Incode fiscal calendar and clamp invalid over-month-end days only when this reproduces the source report.
4. The existing 1.0 SQL maps period 13 to the last day of June and adds one to the source fiscal-year value in gold. Treat both as legacy rules requiring finance-owner confirmation; do not blindly carry them into NextGen.
5. Format target `JournalDate` as `M/D/YYYY` or `MM/DD/YYYY`.
6. Prefer the source post-date for posted actuals only when confirmed. Every date must resolve to an open target period for import.

Zero/invalid dates are blockers unless an approved accounting date replacement exists.

## COA preparation

NextGen dependencies load in this order: Segment Codes → Valid Code Combinations → optional Crosswalk Mapping → Journal Entries.

### Segment Codes (`COA_SEGMENT`)

The source files identify `company` and `control`, but their semantic segment roles are customer-specific. Build rows from the approved segment design:

| Exact target header | Incode9 mapping |
|---|---|
| `Segment Display Name` | Approved segment name such as Fund or Object; must exist on target |
| `Segment Code` | Parsed code from `glc_comp`/`glc_cntl` or the COA crosswalk; uppercase; `^[A-Z0-9_-]+$`; max 50 |
| `Code Description` | `glc_name` / `glhc_name` or approved crosswalk description; max 255 |
| `Account Type` | For Object segment, approved mapping from `glc_type`/`glhc_type`: `1` Asset, `2` Liability, `3` Equity/Fund Balance, `4` Revenue, `5` Expense; exact target value must be confirmed |
| `Tags` | Optional approved semicolon-separated tags |
| `default Parent` | Approved hierarchy lookup; do not derive |
| `Organization Name` | Organization crosswalk from company, else blank only when primary org is intended |

Do not split a legacy account string into target segments by character position unless the segment design explicitly defines those positions.

### Valid Code Combinations (`COA_ACCOUNTS`)

Headers consist of fixed columns plus one exact column per target segment display name:

| Exact fixed header | Incode9 mapping |
|---|---|
| `Description` | `glc_name` / `glhc_name`; required; max 255 |
| `Tags` | Approved semicolon-separated tags |
| `SegmentAll` | Blank unless target design uses it |
| `Budgeting Allowed` | Crosswalk/configuration decision; do not infer from account balance |
| `Posting Allowed` | Map approved `glc_status` rule; source code requires a documented crosswalk |
| `Modules Allowed` | Approved enabled source labels such as `GL;AP`; do not infer |
| `Valid From` | Approved account effective date in `M/D/YYYY`; required |
| `Valid to` | Approved inactive/end date; after Valid From |
| each dynamic segment column | Segment code from the approved `OLD` → target-segments crosswalk |

Every generated target accounting string must equal the crosswalk `NEW` value and exist in the target COA before journal import.

### Crosswalk Mapping (`CROSSWALK_MAPPING`)

Create only when the target import uses external account resolution:

| Exact target header | Mapping |
|---|---|
| `Segment Display Name` | Exact target segment name |
| `External Code` | Corresponding Incode source segment/code |
| `External Code Description` | `glc_name` or crosswalk description |
| `OpenGov Code` | Approved target segment code |
| `OpenGov Code Description` | Target COA description |

For whole-account translation, retain a separate auditable lookup `legacy company-control → NEW Accounting String` even if the target crosswalk template is segment-based.

### Group Hierarchy (`GROUP_HIERARCHY`)

Incode9 account files do not establish the target reporting hierarchy. Generate this template only from an approved hierarchy crosswalk:

| Exact target header | Incode9/approved mapping |
|---|---|
| `Parent` | Approved parent group name; blank only for a root |
| `Child` | Approved group name or segment code; required |
| `Type` | Target GL group type; required and not derivable from `glc_type` |
| `Purpose` | Approved reporting purpose |
| `Segment Display Name` | Exact target segment name when assigning segment codes |
| `Tags` | Approved semicolon-separated tags |
| `Display Name On Report` | Approved report label |
| `Group Code` | Approved group code |
| `Description` | `glc_name`/crosswalk description where applicable |
| `Default Parent` | Approved default parent group |
| `Organization Name` | Exact target org; fund groups permit only the target-supported assignment |

Parent groups, child codes, node types, and relationships must already be valid for the target segment. Without an approved hierarchy crosswalk, report this output as `NOT MAPPED`, not as an import blocker for Journal Entries unless the engagement requires hierarchy migration.

### Fund Account Mapping (`FUND_ACCOUNT_MAPPING`)

System-account roles cannot be inferred from balance, account type, or account name alone. Require a finance-approved fund/system-account crosswalk:

| Exact target header | Mapping |
|---|---|
| `Fund Code` | Approved target fund segment code derived through the COA crosswalk |
| `Change in Fund Balance` | Approved target NET_ACCOUNT accounting string |
| `Fund Balance Account` | Approved target FUND_BALANCE accounting string |
| `Accounts Payable Account` | Approved AP liability accounting string |
| `Retainage Payable Account` | Approved retainage liability accounting string |
| `Payment Discount Account` | Approved discount accounting string |
| `Reserve For Encumbrances Account` | Approved reserve accounting string |
| `Reserve For Pre-Encumbrances Account` | Approved pre-encumbrance reserve string |
| `Cash Account` | Approved cash accounting string |
| `BnP Controlling Account` | Approved Budget & Performance controlling string |

Every populated account must exist in the target COA and belong to the correct fund/type. Never copy the old hard-coded AP cash pseudo-key.

### GL automation templates

No deterministic Incode9 source mapping exists for NextGen automation rules. Create them only from approved target design worksheets.

`GL_AUTOMATION_RULE_INTERFUND_BALANCING`:

| Exact target header | Mapping |
|---|---|
| `Rule Name` | Approved unique rule name |
| `Description` | Approved description |
| `Status` | `ACTIVE` or `INACTIVE` |
| `Allowed Subledgers` | Approved enabled values, pipe-separated |
| `Organization Unit` | Exact target org; blank only for primary |
| `Due To Account` | Approved target accounting string |
| `Due From Account` | Approved target accounting string |

Due-to and due-from accounts must exist, differ, and belong to the same fund.

`GL_AUTOMATION_RULE_CONSOLIDATED_CASH`:

| Exact target header | Mapping |
|---|---|
| `Rule Name` | Approved unique rule name |
| `Description` | Approved description |
| `Status` | `ACTIVE` or `INACTIVE` |
| `Allowed Subledgers` | Approved enabled values, pipe-separated |
| `Consolidated Cash Account` | Approved target accounting string, consistent for the rule |
| `Organization Unit` | Exact target org; blank only for primary |
| `Participating Cash Account` | Approved participating-fund cash string |
| `Claim on Cash Account` | Approved consolidated-fund claim string |

All accounts must exist; consolidated, participating, and claim accounts must satisfy the target fund and uniqueness rules.

## Journal Entry (`JOURNAL_ENTRY`)

Use the exact official template header. Important template typos such as `Reciept ID` and `Asset IDt` must not be corrected.

### Core and descriptive columns

| Exact target header | Incode9 source | Transform / validation |
|---|---|---|
| `Group ID` | source fiscal year + `tran` + `packet` | Stable text; same value on all lines of a JE; required for async |
| `External JE number` | approved combination of `jno`, `tran`, `packet`, and year | Unique in target; do not use row position |
| `Ledger Type` | Constant for actual activity | `Actuals` |
| `TransactionType` | `ttype` through approved target crosswalk | Use `Manual` only when the target JE type combination permits it |
| `JournalDate` | converted `post_date` or approved transaction date | `M/D/YYYY`; open fiscal period |
| `Action Type` | Current template/runtime rule | Leave blank unless required by the template |
| `Accounting String` | COA crosswalk `NEW` from `rtrim(comp)-rtrim(cntl)` | Required; exact active/posting-allowed target account |
| `DebitAmount` | signed `amt` | If `amt > 0`, value rounded to max 2 decimals; else blank |
| `CreditAmount` | signed `amt` | If `amt < 0`, absolute value rounded to max 2 decimals; else blank |
| `Tender Comment` | parsed non-check `ref_no` | Trim; optional |
| `Check No` | parse `ref`: `CHK:` / `CHECK ` | Preserve as text |
| `Contract ID` | source contract extension, if supplied | Target lookup |
| `Invoice No` | `inv` | Preserve text |
| `PO Number` | `po` | Preserve text; target lookup if required |
| `Vendor ID` | crosswalk from `vco + vend` | Do not use the old gold default `0` |
| `Vendor Name` | `APMASTF.apm_name` joined by vendor company/id when `tkey != 'P'` | Trim; descriptive only |
| `JE Source Value` | `journ` through enabled-source crosswalk | Default `GL` only when target configuration confirms it |
| `Organization Name` | company-to-org-unit crosswalk | Exact target org name; blank only for intentional primary-org default |
| `JE Description` | `tran` plus approved packet description | Header value must be consistent within Group ID |
| `JE Line Description` | `descr` | Trim; remove literal quotes only if approved; do not silently truncate |

### Optional subledger metadata

Map only when the current template accepts it and the value has target meaning:

| Target header | Incode9 source / rule |
|---|---|
| `Payment ID` | parsed check/draft reference |
| `Payment Type` / `Pay Method` | `ap_type` or reference prefix through approved crosswalk |
| `Check Date`, `Payment Date`, `Date Paid` | approved source date tied to the payment, not automatically the JE post date |
| `Processed By` | `audit`, if it resolves to an accepted user/text value |
| `Request ID` | `packet_2` or approved request reference |
| `Record Type` | `tkey` through approved crosswalk |
| `Grant ID` | `proj` only when the customer confirms project represents grant |

Leave all other template fields blank unless a supplied Incode column and approved business definition exist: acquisition/asset, bank, benefits, budget identifiers, customer, payroll, receipt, requestor, tender, sale, and useful-life fields. Do not invent mappings from similarly named fields.

For completeness, the default mapping for every remaining official JE column is:

| Exact target header | Default mapping |
|---|---|
| `Acquisition Cost` | Blank; requires fixed-asset source |
| `Acquisition Date` | Blank; requires fixed-asset source |
| `Asset Description` | Blank; requires fixed-asset source |
| `Asset IDt` | Blank; requires fixed-asset source; retain template typo |
| `Bank Account` | Blank; requires target bank-account lookup |
| `Benefit Type` | Blank; requires payroll/benefit source |
| `Budget ID` | Blank for actual GL; map only in approved budget workflow |
| `Budget Name` | Blank for actual GL; map only in approved budget workflow |
| `Customer ID` | Blank; requires AR customer crosswalk |
| `Customer Name` | Blank; requires AR customer source |
| `Depreciation Method` | Blank; requires fixed-asset source |
| `Depreciation Period` | Blank; requires fixed-asset source |
| `Disposal Date` | Blank; requires fixed-asset source |
| `Disposal Method` | Blank; requires fixed-asset source |
| `Earnings Code` | Blank; requires payroll source |
| `Employee ID` | Blank; requires employee crosswalk |
| `Fee Label` | Blank; requires fee source |
| `Gain/Loss` | Blank; requires fixed-asset disposal source |
| `Invoice Date` | Blank unless a joined AP invoice supplies its actual date |
| `Payroll Disbursement` | Blank; requires payroll source |
| `Position Code` | Blank; requires payroll/position source |
| `Receipt Category` | Blank; requires AR/receipt source |
| `Receipt Category Description` | Blank; requires AR/receipt source |
| `Reciept ID` | Blank; requires receipt source; retain template typo |
| `Requestor ID` | Blank; requires procurement/request source |
| `Sale Amount` | Blank; requires fixed-asset sale source |
| `Tender Type` | Blank unless an approved reference-to-tender crosswalk exists |
| `Useful Life` | Blank; requires fixed-asset source |
| `Version` | Blank unless the current template defines a required version |

### Preserve legacy reference detail

The 1.0 SQL built an extended description from reference tokens:

- check `C`, draft `~D`, void `~V`, invoice `~I`, PO `~P`,
- journal note `~N`, transaction type `~T`, project `~J`, project line `~L`.

For NextGen, place readable values in their dedicated columns first. Add a tokenized narrative to `JE Line Description` only when required for historical fidelity and within the target limit.

## Beginning balances

Current `GLCNTLF` and historical `GLHCNTLF` expose `balance` and `bal1`…`bal16`. The existing 1.0 rule calculates:

`beginning_balance = balance - sum(bal1 ... bal16)`

Use this formula only for the confirmed source year and after reconciliation to Incode trial balance. Generate a separate balanced JE batch with:

- unique Group ID and external JE number,
- approved opening date in an open fiscal period,
- accounting string through the COA crosswalk,
- positive amount on debit, negative amount as absolute credit,
- finance-approved balancing/offset lines.

The old hard-coded years (`2022`, `2023`, `2024`) and date `20230930` are examples from one engagement and must never be reused.

## Budget data

For each account/year, the established source amount is:

- current: `sum(glb_bb1 ... glb_bb13)` from `GLBUDGF`, fiscal year `max(GLHBUDGF.glhb_year) + 1`;
- history: `sum(glhb_bb1 ... glhb_bb13)` from `GLHBUDGF`, fiscal year `glhb_year`;
- exclude exact zero totals and map account through the COA crosswalk.

NextGen budgets use `JOURNAL_ENTRY`, not a separate budget template. Classify approved values as Budget Adoption, Amendment, or Transfer; set matching Ledger Type/TransactionType; ensure `budgetingAllowed = true`; and create balanced entries. Do not interpret aggregate annual balances as amendments or transfers without source history.

## Validation gates

1. UTF-8 CSV, exact case-sensitive headers, no blank rows, no currency symbols/group separators, max 200 MB.
2. Dates use `M/D/YYYY`; numbers have at most 2 decimals.
3. Every line has exactly one positive debit or credit and a valid accounting string.
4. Each Group ID has consistent header fields and total debit equals total credit. Never create a balancing plug without written approval.
5. No duplicate external JE number; no duplicated native source row.
6. Org unit, source, ledger, transaction type, JE type combination, fiscal period, and account all resolve in the target entity.
7. Account is active, valid for date, posting allowed, and allows the selected JE source; no prohibited net/system account.
8. Reconcile source and output counts and signed totals by fiscal year, period, company, account, transaction/packet, and grand total.
9. Reconcile beginning balances and annual activity to the Incode trial balance.

For async imports, one failed JE group can reject the whole batch. Return source files/checksums, crosswalk versions, source/output rows and groups, debit/credit totals, exceptions, warnings, and `READY FOR IMPORT` or `NOT READY FOR IMPORT`.
