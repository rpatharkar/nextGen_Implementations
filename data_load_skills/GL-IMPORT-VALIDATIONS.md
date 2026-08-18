# nextGen GL — Import Templates & Validation Guide

**Purpose:** Standalone reference for mapping customer source data into nextGen GL import templates and validating mapped files **before** upload.

**Audience:** Data migration teams, implementation consultants, ETL developers — no access to the application codebase required.

**Version:** 1.1 · May 2026

---

## How to use this document

Use this guide in three phases:

| Phase | What you do | Sections to use |
|-------|-------------|-----------------|
| **1. Prepare target instance** | Confirm master data exists on the GL instance before mapping | [Instance readiness checklist](#instance-readiness-checklist), [Import order](#recommended-import-order) |
| **2. Map source → template** | Transform customer files into one of the 8 GL CSV templates | [Global mapping rules](#global-mapping-rules), [Template specifications](#template-specifications) |
| **3. Validate before import** | Run pre-import checks on mapped CSVs | [Pre-import validation checklist](#pre-import-validation-checklist), per-template **Mapping validation gates** |

> **Key principle:** Fix data during mapping — not after import. Tier 1 errors (format/required) are preventable in ETL. Tier 3 errors (master data) require verifying values against the **target instance** before mapping.

---

## Table of contents

1. [The 8 GL import templates](#the-8-gl-import-templates)
2. [Recommended import order](#recommended-import-order)
3. [Instance readiness checklist](#instance-readiness-checklist)
4. [Global mapping rules](#global-mapping-rules)
5. [Validation tiers (what runs at import)](#validation-tiers-what-runs-at-import)
6. [Pre-import validation checklist](#pre-import-validation-checklist)
7. [Template specifications](#template-specifications)
   - [1. Segment Codes](#1-segment-codes)
   - [2. Valid Code Combinations (COA Accounts)](#2-valid-code-combinations-coa-accounts)
   - [3. Group Hierarchy](#3-group-hierarchy)
   - [4. Fund Account Mapping](#4-fund-account-mapping)
   - [5. Crosswalk Mapping](#5-crosswalk-mapping)
   - [6. Journal Entry](#6-journal-entry)
   - [7. GL Automation — Interfund Balancing](#7-gl-automation--interfund-balancing)
   - [8. GL Automation — Consolidated Cash](#8-gl-automation--consolidated-cash)
8. [Master data lookup reference](#master-data-lookup-reference)
9. [Common mapping mistakes](#common-mapping-mistakes)
10. [Import file delivery requirements](#import-file-delivery-requirements)
11. [Error handling after import](#error-handling-after-import)

---

## The 8 GL import templates

Each template is imported via the GL import API/UI using a `templateType` value. CSV column headers must match the **exact header names** listed below (case-sensitive).

| # | Business name | `templateType` value | Typical source data |
|---|---------------|----------------------|---------------------|
| 1 | Segment Codes | `COA_SEGMENT` | Fund codes, object codes, department codes, project codes |
| 2 | Valid Code Combinations | `COA_ACCOUNTS` | Account strings / accounting combinations |
| 3 | Group Hierarchy | `GROUP_HIERARCHY` | Roll-up / reporting hierarchy relationships |
| 4 | Fund Account Mapping | `FUND_ACCOUNT_MAPPING` | Fund-to-system-account mappings |
| 5 | Crosswalk Mapping | `CROSSWALK_MAPPING` | External-to-OpenGov code crosswalks |
| 6 | Journal Entry | `JOURNAL_ENTRY` | GL transactions, JEs, journal lines |
| 7 | GL Automation — Interfund Balancing | `GL_AUTOMATION_RULE_INTERFUND_BALANCING` | Due-to / due-from automation rules |
| 8 | GL Automation — Consolidated Cash | `GL_AUTOMATION_RULE_CONSOLIDATED_CASH` | Consolidated cash automation rules |

---

## Recommended import order

Dependencies between templates matter. Import in this order to minimize Tier 3 failures:

```
1. Segment Codes          (COA_SEGMENT)
       ↓
2. Valid Code Combinations (COA_ACCOUNTS)     ← requires segment codes to exist
       ↓
3. Group Hierarchy        (GROUP_HIERARCHY)   ← requires segments & groups
       ↓
4. Fund Account Mapping   (FUND_ACCOUNT_MAPPING) ← requires fund codes & COA accounts
       ↓
5. Crosswalk Mapping      (CROSSWALK_MAPPING) ← requires segment codes
       ↓
6. Journal Entry          (JOURNAL_ENTRY)     ← requires COA accounts, open fiscal period
       ↓
7–8. GL Automation rules  (after COA accounts exist)
```

---

## Instance readiness checklist

Before mapping any customer data, verify the **target GL instance** has:

| Item | Where to verify | Required for |
|------|-----------------|--------------|
| COA segments configured (Fund, Object, etc.) | Chart of Accounts setup | Segment Codes, COA Accounts, Group Hierarchy |
| Organization units | GL Settings → Organization Units | JE, Segment Codes, Automation rules |
| Primary organization unit set | GL Settings → Organization Units | Defaults when Organization Name is blank |
| Ledger types | Master data (global) | Journal Entry |
| Transaction types | Master data (global) | Journal Entry |
| JE sources + JE type combinations | GL Settings / master data | Journal Entry |
| JE sources enabled for entity | JE Source Settings | COA Accounts, Automation rules |
| Fiscal calendar + **open periods** | Fiscal Year setup | Journal Entry |
| Fund configuration (mandatory segments) | Fund config | COA Accounts |
| Import templates downloaded | GL UI → Import | Correct column headers |

**Action:** Export or document actual values from the instance (org unit names, segment display names, enabled JE sources) and use them as lookup tables during mapping.

---

## Global mapping rules

Apply these rules when transforming **any** customer source field into a GL template column.

### CSV file rules

| Rule | Requirement |
|------|-------------|
| File format | CSV (UTF-8 recommended) |
| Max file size | 200 MB |
| Column headers | Must match template header names **exactly** (case-sensitive) |
| Empty rows | Remove before import |
| Extra columns | Ignored by import (safe to omit unknown columns) |
| Missing required columns | Import fails |

### Date fields

| Rule | Value |
|------|-------|
| **Required format** | `M/D/YYYY` or `MM/DD/YYYY` |
| Valid examples | `5/29/2026`, `05/29/2026`, `12/1/2025` |
| **Invalid** | `2026-05-29`, `29/05/2026`, `May 29 2026` |

**Mapping transformation:**
```
Source: 2026-05-29  →  Target: 5/29/2026
Source: 20260529    →  Target: 5/29/2026
```

### Boolean fields

Map to any of these (case-insensitive):

| Meaning | Accepted values |
|---------|-----------------|
| True | `true`, `1`, `yes`, `y`, `on`, `Yes` |
| False | `false`, `0`, `no`, `n`, `off`, `No` |

### Array / multi-value fields

Semicolon-separated in a single cell:

```
Tags: "monthly-close;audit;correction"
Modules Allowed: "GL;AP;AR"
```

### Number fields

- No currency symbols: use `100.50` not `$100.50`
- Max 2 decimal places for JE amounts
- No thousands separators: use `1000.00` not `1,000.00`

### String fields

- Trim leading/trailing whitespace
- Do not exceed max length (see per-template specs)
- Preserve exact casing where master data lookup is case-insensitive (org names, ledger types) but segment codes are **uppercase only**

### Blank vs empty

- Leave cell blank for optional fields (do not use `NULL`, `N/A`, `-`, or `#N/A` unless your ETL converts them to blank)
- Required fields must not be blank

### Organization Name

| Scenario | Mapping rule |
|----------|--------------|
| Customer has org/dept name | Map to **exact** org unit name on target instance (case-insensitive match) |
| Customer has no org concept | Leave blank → system uses **primary** org unit |
| Customer org name not in GL | **Create org unit first** or map to existing org unit |

### Defaults (Journal Entry header fields)

When source has no value, you may omit the column or leave blank:

| Column | Default if blank |
|--------|------------------|
| JE Source Value | `GL` |
| Ledger Type | `Actuals` |
| TransactionType | `Manual` |
| Organization Name | Primary org unit |

---

## Validation tiers (what runs at import)

Understanding tiers helps you decide **what to validate during mapping** vs what the system catches at import.

| Tier | Name | When it runs | What mappers should pre-validate |
|------|------|--------------|----------------------------------|
| **Tier 1** | Format / schema | Always | Required fields, data types, lengths, patterns, date format |
| **Tier 2** | Cross-row | **Not active** | N/A — duplicates/uniqueness handled in Tier 3 or writer |
| **Tier 3** | Business rules | Always (or in writer) | Master data exists, fiscal periods open, account combinations valid |

**Mapper responsibility:** Tier 1 + Tier 3 lookups should be validated **before** file delivery.

---

## Pre-import validation checklist

Run this on every mapped CSV before upload:

### File-level

- [ ] Correct `templateType` template used
- [ ] Column headers match specification exactly
- [ ] File encoding is UTF-8
- [ ] No completely empty rows
- [ ] File size under 200 MB
- [ ] Row count within sync limit (see [Import file delivery requirements](#import-file-delivery-requirements))

### Tier 1 (format) — all templates

- [ ] All **required** columns populated on every row
- [ ] All dates in `M/D/YYYY` format
- [ ] String lengths within max limits
- [ ] Segment codes uppercase alphanumeric + `_` `-` only (Segment Codes template)
- [ ] Boolean columns use accepted values
- [ ] No `$` or `,` in numeric fields

### Tier 3 (business) — all templates

- [ ] Referenced master data verified against **target instance**
- [ ] No references to data from a different entity/environment
- [ ] Import order dependencies satisfied (prior templates already imported)

### Template-specific gates

See **Mapping validation gates** under each template below.

---

## Template specifications

Each section provides:
- **Exact CSV headers** (copy into your mapped file)
- **Field mapping spec** (what to map from customer source)
- **Validation rules** (Tier 1 + Tier 3)
- **Mapping validation gates** (pre-import checklist)

---

### 1. Segment Codes

**`templateType`:** `COA_SEGMENT`  
**Import UI:** Chart of Accounts → Segment Codes  
**Sync / Async:** Both supported

#### CSV headers (exact)

```
Segment Display Name, Segment Code, Code Description, Account Type, Tags, default Parent, Organization Name
```

#### Field mapping spec

| CSV Header | Required | Type | Max Length | Pattern / Format | Map from customer source |
|------------|----------|------|------------|------------------|--------------------------|
| **Segment Display Name** | Yes | string | — | Must match segment name on instance (e.g., `Fund`, `Object`, `Department`) | Segment type / dimension name |
| **Segment Code** | Yes | string | 50 | `^[A-Z0-9_-]+$` uppercase only | Fund code, object code, dept code — **convert to uppercase**, remove spaces/special chars |
| **Code Description** | Yes | string | 255 | — | Code description / name |
| Account Type | No* | string | 255 | Required for **Object** segment only | Asset, Liability, Revenue, Expense, etc. |
| Tags | No | array | 500 | Semicolon-separated | Optional tags |
| default Parent | No | string | — | Must exist as segment group on instance | Default roll-up group name |
| Organization Name | No | string | — | Must match org unit on instance; blank = primary | Department / org assignment |

\*Account Type is **required** when Segment Display Name is an Object-type segment.

#### Mapping validation gates

- [ ] Every Segment Display Name exists on target instance
- [ ] All Segment Codes uppercase; no lowercase, spaces, or special characters
- [ ] Code Description ≤ 255 characters
- [ ] Account Type populated for all Object segment rows
- [ ] default Parent group exists (if populated)
- [ ] Organization Name matches instance org unit (if populated)
- [ ] No duplicate Segment Code + Segment Display Name within file
- [ ] No Segment Code already exists in instance (unless intentional update workflow)

#### Tier 3 business rules

- Segment must exist and be active
- Code format must match segment padding/length rules
- Default parent must be active Leaf group belonging to segment
- Object code type required for Object segments; forbidden for others
- Duplicate codes rejected (within batch and database)

---

### 2. Valid Code Combinations (COA Accounts)

**`templateType`:** `COA_ACCOUNTS`  
**Import UI:** Chart of Accounts → Valid Code Combinations  
**Sync / Async:** Both supported

#### CSV headers

**Fixed columns:**
```
Description, Tags, SegmentAll, Budgeting Allowed, Posting Allowed, Modules Allowed, Valid From, Valid to
```

**Plus one column per COA segment** — header = segment **display name** on instance (e.g., `Fund`, `Object`, `Department`, `Project`). These are dynamic; get column list from instance export or template download.

#### Field mapping spec

| CSV Header | Required | Type | Constraints | Map from customer source |
|------------|----------|------|-------------|--------------------------|
| **Description** | Yes | string | 1–255 chars | Account description |
| Tags | No | array | ≤ 500 chars; `[a-zA-Z0-9;,\s_-]*` | Semicolon-separated tags |
| SegmentAll | No | string | — | Rarely used |
| Budgeting Allowed | No | boolean | Yes/No/true/false | Y/N from source |
| Posting Allowed | No | boolean | Yes/No/true/false | Y/N from source |
| Modules Allowed | No | array | ≤ 100 chars; semicolon-separated | `GL;AP;AR` etc. |
| **Valid From** | Yes | date | M/D/YYYY | Account effective start date |
| Valid to | No | date | M/D/YYYY; must be after Valid From | Account end date |
| `{Segment Display Name}` | Varies | string | Segment code value | One column per segment — fund, object, etc. |

#### Mapping validation gates

- [ ] Dynamic segment columns match instance segment display names exactly
- [ ] Description populated, 1–255 chars
- [ ] Valid From in M/D/YYYY format
- [ ] Valid To after Valid From (if populated)
- [ ] Every segment code in row exists and is active on instance
- [ ] Mandatory segments for fund config are populated
- [ ] Modules Allowed uses enabled JE source short labels (`GL`, `AP`, `AR`, etc.)
- [ ] No duplicate account combination within file
- [ ] No duplicate combination already on instance (unless update workflow)

#### Tier 3 business rules

- Valid From < Valid To
- At least one JE source in Modules Allowed
- All segment/code pairs must exist and be active
- Mandatory segments per fund configuration must be present
- Segment org unit must match fund org unit
- No duplicate combinations (batch or database)
- No overlapping validity periods for same combination

---

### 3. Group Hierarchy

**`templateType`:** `GROUP_HIERARCHY`  
**Import UI:** Chart of Accounts → Group Hierarchy  
**Sync only** (async not supported)

#### CSV headers (exact)

```
Parent, Child, Type, Purpose, Segment Display Name, Tags, Display Name On Report, Group Code, Description, Default Parent, Organization Name
```

#### Field mapping spec

| CSV Header | Required | Type | Map from customer source |
|------------|----------|------|--------------------------|
| Parent | No | string | Parent group or roll-up name |
| **Child** | Yes | string | Child group name or segment code |
| **Type** | Yes | string | Hierarchy node type (from GL group types) |
| Purpose | No | string | Group purpose |
| Segment Display Name | Conditional | string | Segment the group/code belongs to |
| Tags | No | array | Semicolon-separated |
| Display Name On Report | No | string | Report label |
| Group Code | No | string | Group code |
| Description | No | string | Description |
| Default Parent | No | string | Default parent group |
| Organization Name | No | string | Comma-separated for multiple orgs |

#### Mapping validation gates

- [ ] Child populated on every row
- [ ] Type populated on every row
- [ ] Segment Display Name matches instance segment (when assigning codes)
- [ ] Parent group exists on instance (if populated)
- [ ] Fund groups: only one Organization Name per fund group

#### Tier 3 business rules

- Segment must exist
- Parent group must exist for segment
- Valid hierarchy node type
- Segment codes eligible for group assignment
- Valid parent-child relationships

---

### 4. Fund Account Mapping

**`templateType`:** `FUND_ACCOUNT_MAPPING`  
**Import UI:** Chart of Accounts → Fund Account Mapping  
**Sync only** · Requires `COA_GL_EDIT` permission

#### CSV headers (exact)

```
Fund Code, Change in Fund Balance, Fund Balance Account, Accounts Payable Account, Retainage Payable Account, Payment Discount Account, Reserve For Encumbrances Account, Reserve For Pre-Encumbrances Account, Cash Account, BnP Controlling Account
```

#### Field mapping spec

| CSV Header | Required | Type | Map from customer source |
|------------|----------|------|--------------------------|
| **Fund Code** | Yes | string | Fund segment code (must exist as Segment Code) |
| Change in Fund Balance | No | string | Formatted accounting string; must be NET_ACCOUNT type |
| Fund Balance Account | No | string | Formatted accounting string; must be FUND_BALANCE type |
| Accounts Payable Account | No | string | Formatted accounting string |
| Retainage Payable Account | No | string | Formatted accounting string |
| Payment Discount Account | No | string | Formatted accounting string |
| Reserve For Encumbrances Account | No | string | Formatted accounting string |
| Reserve For Pre-Encumbrances Account | No | string | Formatted accounting string |
| Cash Account | No | string | Formatted accounting string |
| BnP Controlling Account | No | string | Formatted accounting string |

Account columns use **formatted accounting strings** as they appear in COA (e.g., `101-1234-001-0000`).

#### Mapping validation gates

- [ ] Fund Code exists as fund Segment Code on instance
- [ ] Each account string exists in COA on instance
- [ ] Change in Fund Balance account belongs to same fund and is NET_ACCOUNT type
- [ ] Fund Balance Account belongs to same fund and is FUND_BALANCE type
- [ ] Segment Codes and COA Accounts imported first

#### Tier 3 business rules

- Fund code must exist
- Account strings must resolve to COA accounts
- Account fund must match mapping fund
- Account object types must match role (net vs fund balance)
- Cannot update accounts with existing GL balances

---

### 5. Crosswalk Mapping

**`templateType`:** `CROSSWALK_MAPPING`  
**Import UI:** Crosswalk configuration  
**Sync / Async:** Both supported

#### CSV headers (exact)

```
Segment Display Name, External Code, External Code Description, OpenGov Code, OpenGov Code Description
```

#### Field mapping spec

| CSV Header | Required | Type | Map from customer source |
|------------|----------|------|--------------------------|
| **Segment Display Name** | Yes | string | Segment dimension name on instance |
| External Code | No | string | Customer/legacy system code |
| External Code Description | No | string | Customer code description |
| OpenGov Code | No | string | Matching OpenGov segment code (must exist if populated) |
| OpenGov Code Description | No | string | OpenGov code description |

#### Mapping validation gates

- [ ] Segment Display Name exists on instance
- [ ] OpenGov Code exists for that segment on instance (if populated)
- [ ] Segment Codes imported before crosswalk

#### Tier 3 business rules

- Segment must exist
- OpenGov code must exist and belong to segment (when provided)
- OpenGov code blank = segment-only validation passes

---

### 6. Journal Entry

**`templateType`:** `JOURNAL_ENTRY`  
**Import UI:** Journal Entry Inquiry → Import  
**Sync / Async:** Both (JE Inquiry UI: sync up to **500 rows**, async for larger files)

#### CSV headers (exact)

```
Group ID, External JE number, Ledger Type, TransactionType, JournalDate, Action Type, Accounting String, DebitAmount, CreditAmount, Tender Comment, Acquisition Cost, Acquisition Date, Asset Description, Asset IDt, Bank Account, Benefit Type, Budget ID, Budget Name, Check Date, Check No, Contract ID, Customer ID, Customer Name, Date Paid, Depreciation Method, Depreciation Period, Disposal Date, Disposal Method, Earnings Code, Employee ID, Fee Label, Gain/Loss, Grant ID, Invoice Date, Invoice No, Pay Method, Payment Date, Payment ID, Payment Type, Payroll Disbursement, PO Number, Position Code, Processed By, Receipt Category, Receipt Category Description, Reciept ID, Record Type, Request ID, Requestor ID, Sale Amount, Tender Type, Useful Life, Vendor ID, Vendor Name, Version, JE Source Value, Organization Name, JE Description, JE Line Description
```

> Note: Header `Reciept ID` is spelled as shown (typo in template — do not "fix" it).

#### Minimum viable mapping (required columns only)

For a basic JE import, at minimum map:

| CSV Header | Required | Notes |
|------------|----------|-------|
| **Group ID** | Recommended | Same value groups lines into one JE; required column for async import |
| **JournalDate** | **Yes** | M/D/YYYY |
| **Accounting String** | **Yes** | Must exist in COA |
| DebitAmount | Line level | One of debit or credit per line |
| CreditAmount | Line level | One of debit or credit per line |

#### Key optional header fields

| CSV Header | Default if blank | Valid values (from instance master data) |
|------------|------------------|----------------------------------------|
| Ledger Type | `Actuals` | See [Ledger types](#ledger-types) |
| TransactionType | `Manual` | See instance transaction types |
| JE Source Value | `GL` | See [JE source short labels](#je-source-short-labels) |
| Organization Name | Primary org unit | Exact org unit name on instance |
| External JE number | Auto-generated | Must be unique if provided |

#### Line-level mapping rules

| Rule | Requirement |
|------|-------------|
| One JE per Group ID | All lines with same Group ID = one journal entry |
| Header fields | Take from first row of each Group ID group |
| Debit OR credit | Each line: debit > 0 **or** credit > 0, not both |
| Amounts | Non-negative; max 2 decimal places |
| Accounting String | Must exist in COA with write access |

#### Mapping validation gates

- [ ] Group ID assigned to group related lines
- [ ] JournalDate in M/D/YYYY format on every row
- [ ] Accounting String populated on every row
- [ ] Accounting String exists in COA on instance
- [ ] Ledger Type = exact display name (e.g., `Actuals` not `Actual`)
- [ ] Organization Name matches instance org unit (if populated)
- [ ] JE Source + Ledger Type + TransactionType combination exists as JE Type on instance
- [ ] Fiscal period open for JournalDate
- [ ] Debit/credit rules satisfied per line
- [ ] External JE number unique (if populated)
- [ ] COA Accounts imported before JE
- [ ] For async: Group ID column present in file

#### Tier 3 business rules

**Header:** org unit, JE source enabled, ledger/transaction types, JE type combo, fiscal period open, subledger period (non-GL), external JE number unique, crosswalk resolution (if crosswalk selected at import)

**Lines:** amount rules, COA account exists/active/posting allowed, account config valid for date, JE source allowed for account, org unit match, no NET_ACCOUNT on lines

**Async atomicity:** If any JE group in batch fails, entire batch rejected

---

### 7. GL Automation — Interfund Balancing

**`templateType`:** `GL_AUTOMATION_RULE_INTERFUND_BALANCING`  
**Sync only** · Rows with same **Rule Name** = one rule

#### CSV headers (exact)

```
Rule Name, Description, Status, Allowed Subledgers, Organization Unit, Due To Account, Due From Account
```

#### Field mapping spec

| CSV Header | Required | Type | Constraints | Map from customer source |
|------------|----------|------|-------------|--------------------------|
| **Rule Name** | Yes | string | 1–255 chars | Rule identifier; groups rows |
| Description | No | string | ≤ 1000 chars | Rule description |
| **Status** | Yes | string | `ACTIVE` or `INACTIVE` | Rule status |
| **Allowed Subledgers** | Yes | string | Pipe-separated: `AP\|AR` | Enabled subledgers |
| Organization Unit | No | string | ≤ 255 chars; blank = primary | Org unit name |
| **Due To Account** | Yes | string | Formatted COA string | Due-to account |
| **Due From Account** | Yes | string | Formatted COA string | Due-from account |

#### Mapping validation gates

- [ ] Rule Name consistent across rows belonging to same rule
- [ ] Status is `ACTIVE` or `INACTIVE`
- [ ] Allowed Subledgers pipe-delimited; subledgers enabled on instance
- [ ] Due To and Due From accounts exist in COA
- [ ] Due To and Due From belong to **same fund**
- [ ] No duplicate due-to or due-from within a rule
- [ ] Due-to ≠ due-from on same row
- [ ] Rule Name not already on instance
- [ ] COA Accounts imported first

#### Tier 3 business rules

- Rule name unique in database
- Group-level field consistency across rows
- Account existence, org unit, not system account
- Fund constraints and cross-rule conflict checks
- All-or-none: any failure rolls back entire import

---

### 8. GL Automation — Consolidated Cash

**`templateType`:** `GL_AUTOMATION_RULE_CONSOLIDATED_CASH`  
**Sync only** · Rows with same **Rule Name** = one rule

#### CSV headers (exact)

```
Rule Name, Description, Status, Allowed Subledgers, Consolidated Cash Account, Organization Unit, Participating Cash Account, Claim on Cash Account
```

#### Field mapping spec

| CSV Header | Required | Type | Constraints | Map from customer source |
|------------|----------|------|-------------|--------------------------|
| **Rule Name** | Yes | string | 1–255 chars | Rule identifier |
| Description | No | string | ≤ 1000 chars | Rule description |
| **Status** | Yes | string | `ACTIVE` or `INACTIVE` | Rule status |
| **Allowed Subledgers** | Yes | string | Pipe-separated | Enabled subledgers |
| **Consolidated Cash Account** | Yes | string | Formatted COA string | Consolidated fund cash account |
| Organization Unit | No | string | blank = primary | Org unit name |
| **Participating Cash Account** | Yes | string | Formatted COA string | Participating fund cash account |
| **Claim on Cash Account** | Yes | string | Formatted COA string | Claim-on-cash account |

#### Mapping validation gates

- [ ] Rule Name consistent within rule group
- [ ] Consolidated Cash Account same on all rows of a rule
- [ ] All three account types exist in COA
- [ ] No duplicate participating cash account within rule
- [ ] Participating ≠ Claim on same row
- [ ] Consolidated account ≠ participating or claim accounts
- [ ] Claim account belongs to consolidated fund
- [ ] COA Accounts imported first

#### Tier 3 business rules

Same pattern as Interfund Balancing (unique rule name, group consistency, account/fund validation, all-or-none rollback).

---

## Master data lookup reference

Values must match the **target instance**. Export from instance or use GL Settings screens.

### Ledger types

Use exact **display name** (case-insensitive):

| Display Name |
|--------------|
| Budget Adoption |
| Budget Amendment |
| Budget Transfer |
| Pre-encumbrance |
| Encumbrance |
| **Actuals** |

> Common error: `Actual` → must be **`Actuals`**

### JE source short labels

| Short Label | Typical meaning |
|-------------|-----------------|
| GL | General Ledger |
| AP | Accounts Payable |
| AR | Accounts Receivable |
| PR | Payroll |
| BR | Budget |
| BnP, PRO, CR, UB, PLC, FA, TnR | Entity-specific |

Use only sources **enabled** in JE Source Settings.

### Transaction types

Default for JE import: **`Manual`**

Full list is entity/global master data. Common values include: Manual, Budget Adoption, Invoice Accrual, Invoice Payment, Payroll Accrual, Addition, Reclassification, Depreciation, Adjustment, Year end closure, Allocation.

### Organization units

- Match **Name** field from GL Settings → Organization Units
- Case-insensitive
- Blank → primary org unit

---

## Common mapping mistakes

| Mistake | Fix during mapping |
|---------|-------------------|
| Dates as `YYYY-MM-DD` | Convert to `M/D/YYYY` |
| Ledger Type = `Actual` | Use `Actuals` |
| Organization name from customer not in GL | Create org unit or map to existing |
| Segment codes lowercase | Convert to UPPERCASE |
| Segment codes with spaces/special chars | Remove or replace with `_` or `-` |
| Accounting string doesn't exist yet | Import Segment Codes → COA Accounts first |
| JE imported before COA | Follow [import order](#recommended-import-order) |
| `$1,000.00` in amount fields | Strip `$` and `,` → `1000.00` |
| Both debit and credit on same line | Map to one side only |
| `NULL` / `N/A` in required fields | Convert to blank (optional) or valid value (required) |
| Wrong CSV header spelling | Use exact headers from this doc (e.g., `Reciept ID`) |
| Crosswalk OpenGov code doesn't exist | Import segment code first |
| Async JE without Group ID column | Add Group ID column |

---

## Import file delivery requirements

| Setting | Value |
|---------|-------|
| File format | CSV (UTF-8) |
| Max size | 200 MB |
| Sync row limit (general UI) | 1,000 rows |
| Sync row limit (Journal Entry Inquiry) | 500 rows |
| Larger files | Use async import mode |
| Async not supported | Group Hierarchy, Fund Account Mapping |

**API import parameter:** `templateType` = one of the 8 values in [The 8 GL import templates](#the-8-gl-import-templates)

**Optional JE import parameter:** `crosswalkName` — when importing JEs with external accounting strings

---

## Error handling after import

Even with pre-validation, some errors may appear at import:

| Error prefix | Tier | Action |
|--------------|------|--------|
| `Validation Error: ...` | Tier 1 | Fix format/required in mapped file and re-import |
| Business message (no prefix) | Tier 3 | Verify master data on instance; fix mapping lookup |
| `Rule "X": ...` | Writer | Fix automation rule grouping/consistency |

**Sync import:** Error CSV downloaded as `{filename}_errors.csv` with original row + error column.

**Async import:** Error file available from import job status when complete.

**Remediation workflow:**
1. Download error file
2. Identify Tier 1 vs Tier 3 failures
3. Fix mapping transformation rules
4. Re-generate CSV
5. Re-run [pre-import validation checklist](#pre-import-validation-checklist)
6. Re-import

---

## Mapping worksheet template

Use this structure for each customer source → GL template mapping:

```markdown
### Mapping: [Customer File Name] → [Template Name]

**templateType:** COA_SEGMENT | COA_ACCOUNTS | ...

| Source column | Source example | Target CSV header | Transformation rule | Required | Validation gate |
|---------------|----------------|-------------------|---------------------|----------|-----------------|
| FUND_CD       | 101            | Segment Code      | UPPER(), trim       | Yes      | Exists as Fund segment |
| FUND_DESC     | General Fund   | Code Description  | trim, max 255       | Yes      | Length check |
| ...           |                |                   |                     |          |                 |

**Lookup tables needed:** [org units export, segment list, etc.]
**Depends on:** [templates that must be imported first]
**Estimated row count:** N
**Import mode:** sync / async
```

---

*Standalone document for nextGen GL data migration. Compatible with use outside the application repository.*
