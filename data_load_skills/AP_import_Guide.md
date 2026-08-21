# OpenGov NextGen Accounts Payable Data Import Guide

Portable mapping, validation, migration, and operating guide for importing
Accounts Payable invoices and payments into OpenGov NextGen. This document is
self-contained and can be copied outside the source repository.

**Covered imports**

- Live invoices: `live-invoices` / `INVOICES_LIVE`
- Historical invoices: `historical-invoices` / `HISTORICAL_INVOICES`
- Historical payments: `historical-payments` / `HISTORICAL_PAYMENTS`

**Legend:** `*` = required; `**` = either-or; `Conditional` = required when the
stated condition applies.

> **Fail-closed rule:** Never approve or upload a workbook unless its structure,
> data, totals, references, duplicates, and target-instance configuration have
> all been validated. If the current target-instance template or required
> reference data is unavailable, report **NOT READY FOR IMPORT**.

> **Runtime authority:** Import contracts can change. The current template
> downloaded from the target OpenGov instance and the target runtime validator
> override this guide. Never add, remove, rename, or reorder template columns.

---

## 1. Select the correct import

| Business need | Import | Workbook shape | Access |
| --- | --- | --- | --- |
| Open, current, or payable invoices that must enter normal AP processing | `live-invoices` | `Instructions` plus flat `Invoice Import`; one row per GL distribution | AP users with import permission |
| Legacy invoices retained for conversion/history | `historical-invoices` | Header, line, and distribution sheets | OpenGov employees or authorized migration personnel |
| Legacy payments already issued in the old system | `historical-payments` | `payments` plus `payment_invoices` | OpenGov employees or authorized migration personnel |

Do not use historical imports to bypass normal invoice approval or payment
controls. For an unusual legacy layout, transform it into the current
`live-invoices` template unless an authorized migration plan specifically
requires historical imports.

### Import dependencies

Use this order for a migration:

1. Configure entities, organization units, fiscal calendars, payment terms,
   payment methods, banks, chart of accounts, projects, and vendors.
2. Load and validate historical invoices.
3. Load historical payments only after their invoice keys exist.
4. Load open/live invoices.
5. Reconcile and sign off each batch before starting the next dependent batch.

---

## 2. Roles, ownership, and approvals

Assign named owners before preparing data:

| Role | Responsibility |
| --- | --- |
| Business owner | Defines scope, balances, cutover date, and acceptance criteria |
| Source-system owner | Produces complete, repeatable source extracts |
| AP subject-matter expert | Approves status, type, payment, retainage, tax, and PO mappings |
| GL/finance owner | Approves org-unit, fiscal-period, GL, project, and control-total mapping |
| Vendor owner | Confirms vendor identity, status, remit address, terms, and methods |
| Data mapper | Maintains source-to-target mapping and transformation rules |
| Validator/reviewer | Independently checks structure, data rules, and reconciliations |
| Import operator | Uses least-privilege access to upload approved files |
| Approver | Signs the readiness record and post-import reconciliation |

The person who prepares a production workbook should not be its only reviewer.
Keep source extracts immutable and version transformed outputs.

---

## 3. Required inputs before mapping

Obtain all of the following for the target entity and environment:

- Current blank template downloaded from the target instance.
- Import type, entity, environment, cutover date, and expected record count.
- Source data dictionary, extract logic, extraction timestamp, and control totals.
- Active organization units and their target identifiers/names.
- Vendors with OpenGov ID, external code, approval status, remit addresses,
  payment terms, and non-deleted payment methods.
- Active payment terms and configured vendor payment methods.
- Fiscal years and periods covering every accounting/accrual date.
- Valid GL account strings and project-account strings.
- Existing invoice duplicate keys: organization unit, vendor, and vendor invoice number.
- PO headers, lines, and distributions for every PO-linked invoice.
- Bank and bank-account configuration for manual/external checks.
- For historical payments: existing invoice keys, invoice amounts, currency, and hold status.

If any required reference set is missing or stale, stop. Do not infer target IDs,
accounts, vendors, or payment settings from labels alone.

---

## 4. File and workbook rules

### Upload gates

- File must be a non-empty `.xlsx` workbook.
- Maximum file size is **30 MB**.
- Do not rename the import type/slug.
- Workbook must open without repair warnings.
- Do not use `.csv`, `.xls`, macro-enabled files, password protection, or external links.
- Remove hidden rows/columns, merged header cells, comments used as data, subtotals,
  pivot tables, filters that hide records, and unresolved formula errors.
- Prefer values rather than formulas in import data cells.
- Preserve identifier fields as text so leading zeros are not lost.
- Use unambiguous dates. For live workbooks use **MM/DD/YYYY**.
- Preserve template sheet count, position, headers, capitalization, and data-start row.
- Do not insert blank records inside a contiguous data range.

### Validation layers

| Layer | Purpose | Examples |
| --- | --- | --- |
| L1 | Required values, type, format, enum, and length | Required org unit, numeric amount, valid date |
| L2 | Cross-field, arithmetic, and business rules | Header equals lines, distribution totals, date order |
| L3 | Target-instance reference checks | Vendor, org unit, account, project, term, PO |

Passing workbook structure alone does not mean the data is import-ready.

### Import statuses

Expected job statuses include `QUEUED`, `RUNNING`, `ERRORED`, `FAILED`,
`CANCELLED`, `SUCCESSFUL`, and `PARTIALSUCCESS`. Result files are normally
available after the job leaves `QUEUED` or `RUNNING`.

---

## 5. Live invoice import

**Workbook:** `Instructions` and `Invoice Import`  
**Header row:** row 2 of `Invoice Import`  
**Data begins:** row 3  
**Grain:** one row per GL distribution. Repeat invoice and line values on every
distribution row.

The current live layout contains 64 import columns. Preserve the target
template's exact order even if a label shown below differs from a newer template.

### 5.1 Invoice header columns

| Target column | Requirement | Validation |
| --- | --- | --- |
| Organization Unit* | Required | Must resolve to an active organization unit in the target entity |
| Vendor ID** | Either-or | Supply Vendor ID or Vendor External System Code; if both are supplied, both must identify the same approved vendor |
| Vendor External System Code** | Either-or | Must resolve uniquely to the vendor |
| Vendor Invoice Number* | Required | Text; maximum 40 characters; unique for org unit plus vendor |
| Invoice Type* | Required | Template-approved enum; commonly `STANDARD`, `CREDIT_MEMO`, `RETAINAGE_RELEASE` |
| Invoice Amount* | Required | Numeric; sign must match type; must equal resolved line total |
| Remit To Addr Line 1 | Optional | If supplied, remit fields must match an address for the vendor |
| Remit To Addr Line 2 | Optional | Same vendor-address rule |
| Remit To City | Optional | Same vendor-address rule |
| Remit To State | Optional | Use target-accepted state code, commonly two characters |
| Remit To Zip | Optional | Preserve as text; must match vendor remit address |
| Invoice Date* | Required | `MM/DD/YYYY`; not future |
| Received Date | Optional/defaulted | `MM/DD/YYYY`; not before invoice date or after today |
| Accrual JE Date | Optional/defaulted | `MM/DD/YYYY`; must resolve to a configured fiscal period |
| Invoice Description | Optional | Current batch guidance: maximum 500 characters |
| Payment Term | Optional/defaulted | Must be active; blank uses vendor default where supported |
| Payment Method | Optional/defaulted | Must exist as a non-deleted method on the vendor |
| Bank Name | Conditional | Manual/external check only; must resolve in AP settings |
| Bank Account Name | Conditional | Manual/external check only; must resolve for the bank |
| Check Payee Name | Conditional | Required for a manual check |
| Check Number | Conditional | Required for a manual check; digits-only where runtime requires |
| Check Date | Conditional | Required for a manual check; not before invoice date |
| Check Amount | Conditional | Required for a manual check; positive and reconciled |
| Due Date Override | Optional | Valid date; not before invoice date |
| Separate Payment | Optional | `Y` or `N`; default `N` |
| Retainage % (Default) | Optional | Numeric from 0 through 100; prohibited for credit memos |
| Tags | Optional | Comma-separated; validate current per-tag and total limits |
| Action* | Required | `Draft` or `Submit` |
| External Invoice Reference # | Optional | Maximum 255 characters |

### 5.2 Invoice line columns

| Target column | Requirement | Validation |
| --- | --- | --- |
| Line #* | Required | Integer at least 1; unique within invoice |
| Line Type* | Required | `ITEM`, `SERVICE`, `FREIGHT`, `TAX`, `DISCOUNT`, `MISC`, or template-approved `RETAINAGE` |
| Line Description* | Required | Nonblank; trim whitespace |
| PO # | Optional | If supplied, PO must exist for resolved vendor |
| PO Line # | Conditional | Required when PO # is supplied; must exist on PO |
| Contract # | Optional | Validate against target contract if used |
| Unit of Measure | Optional | Maximum 64 characters; target-approved abbreviation |
| Quantity* | Required for quantity-based line | Numeric and within supported range |
| Unit Price* | Required for quantity-based line | Numeric and within supported range |
| Extended Amount | Calculated/optional | Quantity multiplied by Unit Price at cent precision |
| Discount Amount | Optional | Numeric; formula and line-type rules apply |
| Freight Amount | Optional | Numeric; formula and line-type rules apply |
| Sales Tax Amount | Optional | Numeric; formula and line-type rules apply |
| Misc. Charge Amount | Optional | Numeric; formula and line-type rules apply |
| Line Subtotal | Calculated/optional | Extended minus absolute discount plus freight, sales tax, and misc |
| Use Tax Applicable | Optional | `Y` or `N`; default `N` |
| Use Tax Rate % | Conditional | Required when Use Tax Applicable is `Y`; 0 through 100 |
| Use Tax Amount | Calculated/optional | Must agree with applicable base and rate |
| Line Retainage % | Optional | 0 through 100; overrides header default |
| Line Retainage Amount | Calculated/optional | Must agree with base and percentage |
| Net Line Amount | Calculated/optional | Must agree with subtotal, tax, and retainage behavior |
| External Line Reference # | Optional | Maximum 255 characters |
| Part # | Optional | Maximum 128 characters |
| Manufacturer | Optional | Maximum 255 characters |
| Model | Optional | Maximum 128 characters |
| Serial # | Optional | Maximum 128 characters |
| List Price | Optional | Numeric |

### 5.3 GL distribution columns

| Target column | Requirement | Validation |
| --- | --- | --- |
| GL Distribution #* | Required | Integer at least 1; unique within parent line |
| GL Account* | Required for non-PO distribution | Must resolve in the target entity's chart of accounts |
| Project Account | Optional | Must resolve when supplied |
| PO Distribution # | Optional/derived | If supplied, must exist on the resolved PO line |
| Distribution % ** | Either-or | Numeric 0 through 100; line total must equal 100 within accepted tolerance |
| Distribution Amount ** | Either-or | Numeric; line total must equal the applicable line amount |
| Reimbursable | Optional | `Y` or `N`; default `N` |
| External Distribution ID | Optional | Maximum 255 characters |

When both distribution percent and amount are provided, they must agree:

`Distribution Amount = Line Amount × Distribution % / 100`

One distribution may absorb a one-cent rounding remainder. For money-exact
migrations, using distribution amounts consistently is usually safer than
recomputing percentages.

### 5.4 Live invoice calculations

- Invoice Amount equals the sum of resolved line amounts.
- Quantity × Unit Price equals Extended Amount for quantity-based lines.
- Line Subtotal equals Extended Amount − absolute Discount Amount + Freight
  Amount + Sales Tax Amount + Misc. Charge Amount.
- Distribution amounts equal the applicable line amount.
- Distribution percentages total 100% per line.
- Header retainage equals the sum of line retainage where both are supplied.
- Use-tax and retainage percentages must be from 0 through 100.
- Common money tolerance is **0.005**; common unit-price tolerance is **0.01**.
  Apply the stricter target-runtime rule if it differs.

### 5.5 PO invoice rules

- PO must belong to the resolved invoice vendor.
- PO Line # is mandatory when PO # is populated.
- PO line and PO distribution must exist and be available for invoicing.
- A PO-linked distribution may be defaulted from the PO split when permitted.
- If GL account, project account, percentage, or amount is supplied for a PO
  split, it must match the resolved PO distribution.
- Do not mix PO and non-PO accounting without explicit business approval and
  support in the target template.

### 5.6 Credit memo rules

- Header amount is strictly negative.
- Quantity is negative and unit price is positive for quantity-based credit lines.
- Nonzero extended, subtotal, freight, misc, sales-tax, net-line, and
  distribution amounts follow the negative sign.
- Discount line type and nonzero Discount Amount are prohibited.
- Retainage percentage and amount are prohibited.
- Header, line, and distribution totals must reconcile by both sign and magnitude.

### 5.7 Retainage release rules

Template and runtime support can differ. Treat `RETAINAGE_RELEASE` as
**NOT READY** until the target instance confirms it is accepted.

Where supported:

- `RETAINAGE` lines are used only for retainage-release invoices.
- Retainage-release invoices contain only retainage lines.
- PO fields are not populated unless the current template explicitly permits them.

### 5.8 Manual/external check rules

- Bank/check fields are used only for the target's manual/external payment method.
- Bank Name, Bank Account Name, Check Amount, Check Date, Check Payee Name, and
  Check Number are required for a manual check.
- Check Amount is positive; Check Date is not before Invoice Date.
- Bank and account must resolve in AP settings.
- The same bank and check number must use one amount and one date.
- A check number cannot be reused across different banks.
- Sum of invoice amounts sharing a check equals Check Amount within 0.005.

---

## 6. Historical invoice import

**Access:** restricted migration function  
**Shape:** multi-sheet `.xlsx`  
**Sheet matching:** by position. Sheet 1 is required; child sheets are optional
only when the target template permits. If child data is included, keys must join
without orphans.

### 6.1 Sheet 1: invoice header

Headers are exact and order-sensitive:

| Pos | Exact header | Requirement | Rule |
| --- | --- | --- | --- |
| A | Invoice Key | Conditional | Max 64; required with child sheets; unique |
| B | Org Unit | Required | Max 255; must resolve |
| C | Invoice Type | Required | Max 32; accepted historical enum |
| D | Inv Amt | Required | Numeric; sign and balance rules |
| E | Vendor External Code | Either-or | Max 64; E or F must resolve |
| F | Vendor Name | Either-or | Max 255; if both E and F supplied, same vendor |
| G | Remit To Addr Line 1 | Conditional | Max 255; required unless Status is `PAID` |
| H | Addr Line 2 | Optional | Max 255 |
| I | City | Conditional | Max 100; required unless `PAID` |
| J | State | Optional | Max 16 |
| K | Zip | Conditional | Max 16; required unless `PAID` |
| L | Vendor Inv No | Required | Max 40; duplicate-key component |
| M | Inv Date | Required | Accepted historical date; not future |
| N | Received Date | Optional | Between invoice date and today |
| O | Accrual JE Date | Required | Must map to fiscal period; before invoice date may warn |
| P | Description | Optional | Max 10,000 |
| Q | Payment Term | Required | Max 255; active and resolvable |
| R | Payment Method | Optional | Max 64; must exist on vendor |
| S | Due Date Override | Optional | Valid date; not before invoice; literal `NULL` may be treated blank |
| T | Separate Payment Flag | Optional | Boolean-compatible value |
| U | Retainage Percent | Optional | Numeric 0 through 100 |
| V | Invoice Source | Optional | `IMPORT`, `LEGACY_IMPORT`, or `MANUAL` |
| W | Tag | Optional | Max 100 |
| X | Status | Optional | Accepted historical status |
| Y | External Inv Ref | Optional | Max 255 |

Historical invoice types commonly accepted case-insensitively:
`STANDARD`, `CREDIT_MEMO`, `DEBIT_MEMO`, `PREPAYMENT`,
`RETAINAGE_RELEASE`.

Historical statuses commonly accepted case-insensitively:
`DRAFT`, `PENDING_REVIEW`, `PENDING_APPROVAL`, `APPROVED`, `REJECTED`,
`ACCRUED`, `PARTIALLY_PAID`, `PAID`, `VOIDED`, `CANCELLED`.

### 6.2 Sheet 2: invoice lines

Exact 28-column order:

`Invoice Key`, `Invoice Line`, `Line Type`, `Description`, `PO Number`,
`PO Line Number`, `Contract Number`, `UOM`, `Quantity`, `Unit Price`,
`Extended Amount`, `Discount Amount`, `Freight Amount`, `Sales Tax Amount`,
`Misc Charge Amount`, `Line Subtotal`, `Use Tax Applicable`,
`Use Tax Rate Pct`, `Use Tax Amount`, `Retainage Pct`, `Retainage Amount`,
`Net Line Amount`, `External Line Reference`, `Part Number`, `Manufacturer`,
`Model`, `Serial`, `List Price`.

Required fields: Invoice Key, Invoice Line, Line Type, Description, Quantity, and
Unit Price. PO Line Number is required when PO Number is supplied. Amount,
quantity, rate, and price fields must parse as numeric. Percentages are 0 through
100. Use Tax Rate Pct is required when Use Tax Applicable is true or `Y`.

### 6.3 Sheet 3: invoice GL distributions

Exact 10-column order:

`Invoice Key`, `Invoice Line`, `GL Distribution No`, `GL Account`,
`Project Account`, `PO Distribution Number`, `Percent`, `Amount`,
`Reimbursable`, `External Dist Id`.

Invoice Key, Invoice Line, GL Distribution No, and GL Account are required.
Percent or Amount is required. Percent is 0 through 100. Percentages total
**100 ±0.01** per line; amounts total the calculated net line amount within
**0.01**. GL and project accounts must resolve.

### 6.4 Historical invoice cross-sheet rules

- Invoice Key is unique among headers.
- Every line Invoice Key matches one header.
- Invoice Line is unique within Invoice Key.
- Every distribution `(Invoice Key, Invoice Line)` matches one line.
- GL Distribution No is unique within its line.
- Header amount equals resolved line total within 0.01.
- Credit memo amount is negative; other invoice-type amounts are positive.
- `(entity, org unit, vendor, vendor invoice number)` is unique both in the
  workbook and existing AP invoices.
- Invoice date is not future.
- Accrual JE Date resolves to a configured fiscal period.

---

## 7. Historical payment import

Exactly two sheets are required. Headers are validated by position and text
after trim/case normalization. Use one `payments` row per Payment Number and one
or more `payment_invoices` rows per Payment Number.

### 7.1 Sheet: payments

| Pos | Exact header | Requirement | Rule |
| --- | --- | --- | --- |
| 1 | Vendor External Code | Required | Max 255; uniquely resolves vendor |
| 2 | Payment Number | Required | Max 64; unique workbook mapping key |
| 3 | Invoice Amount | Required | Numeric and strictly greater than zero |
| 4 | Early Pay Discount | Required | Numeric and non-negative |
| 5 | Payment Amount | Required | Invoice Amount minus discount within 0.01 |
| 6 | Payee Name | Optional | Max 255 |
| 7 | Payment Method | Required | Max 64; exists on vendor |
| 8 | Remit To Addr Line 1 | Optional | Max 255 |
| 9 | Addr Line 2 | Optional | Max 255 |
| 10 | City | Optional | Max 255 |
| 11 | State | Optional | Max 64 |
| 12 | Zip | Optional | Max 32; preserve as text |
| 13 | ACH Bank Name | Method-dependent | Max 255 |
| 14 | ACH Account Type | Method-dependent | Max 64 |
| 15 | ACH Account Number | Sensitive/method-dependent | Max 64 |
| 16 | ACH Routing Number | Sensitive/method-dependent | Max 64 |
| 17 | ACH Account Holder Name | Method-dependent | Max 255 |
| 18 | ACH Email Address | Method-dependent | Max 255 |
| 19 | Currency | Required | Three-character code; matches invoices |
| 20 | Payment Reference Number | Optional | Max 255; duplicate detection applies |
| 21 | Issue Date | Optional | Not after Payment Date |
| 22 | Payment Date | Required | Not future; resolves payment run |
| 23 | Cleared Date | Optional | Not before Payment Date |
| 24 | Check Bank Name | Check-dependent | Max 255 |
| 25 | Check Bank Account Number | Sensitive/check-dependent | Max 64 |
| 26 | Check Number | Check-dependent | Max 64; duplicate detection applies |
| 27 | Status | Required | `ISSUED`, `CLEARED`, or `VOIDED` |

### 7.2 Sheet: payment_invoices

| Pos | Exact header | Requirement | Rule |
| --- | --- | --- | --- |
| 1 | Payment Number | Required | Max 64; matches exactly one payments row |
| 2 | Invoice Key | Required | Max 100; uniquely resolves an existing AP invoice |

### 7.3 Historical payment cross-sheet rules

- Every Payment Number is unique on `payments`.
- Every payment has at least one invoice link.
- Every link Payment Number exists on `payments`.
- Every `(Payment Number, Invoice Key)` pair is unique.
- Vendor code is nonblank and resolves uniquely.
- Payment method is active/non-deleted on the vendor.
- Payment Date resolves to a payment run.
- `Payment Amount = Invoice Amount − Early Pay Discount` within 0.01.
- Linked Invoice Key exists uniquely and invoice is not on hold.
- Payment currency equals every linked invoice currency.
- Invoice Amount equals the exact sum of linked invoice amounts.
- Check Number and Payment Reference Number are not duplicated.
- Payment Number is a workbook mapping key; NextGen may generate the stored
  payment number.

Payment workbooks can contain bank account, routing, payee, and address data.
Treat them as restricted financial data.

---

## 8. Common validation rules

### 8.1 Formats and ranges

| Field | Rule |
| --- | --- |
| Live workbook date | `MM/DD/YYYY` |
| API JSON date | `YYYY-MM-DD`; do not reuse API format in a workbook |
| Vendor invoice number | Maximum 40 |
| PO number / UOM | Maximum 64 |
| External line reference | Maximum 255 |
| Part / model / serial | Maximum 128 |
| Manufacturer | Maximum 255 |
| Quantity | Common quantity-based range 0.0001 through 999,999,999; credit rules may require negative quantity |
| Unit price | Common range 0.0001 through 999,999,999.99 |
| Line amount | Common range -999,999,999.99 through 999,999,999.99 |
| Retainage and use-tax percentage | 0 through 100 |

### 8.2 Date rules

- Invoice Date is not future.
- Invoice Date older than one year may produce a warning.
- Received Date is on or after Invoice Date and not future.
- Accounting/Accrual JE Date before Invoice Date may warn.
- Due Date is on or after Invoice Date.
- Discount Date is on or before Due Date.
- Payment Issue Date is not after Payment Date.
- Cleared Date is not before Payment Date.

### 8.3 Identity and duplicates

| Grain | Identity |
| --- | --- |
| Invoice | Organization Unit + Vendor + Vendor Invoice Number |
| Line | Invoice identity + Line # |
| Distribution | Invoice and line identity + GL Distribution # |
| Historical invoice | Invoice Key across sheets |
| Historical payment | Payment Number across sheets; Invoice Key on link |

Normalize only for comparison; do not silently alter source identifiers. Compare
after trim and use target-runtime case rules. Check duplicates both inside the
workbook and against existing target records.

### 8.4 Reference checks

- Organization unit exists, is active, and belongs to the target entity.
- Vendor resolves uniquely, is approved where required, and supplied identifiers agree.
- Remit address belongs to the resolved vendor.
- Payment term is active.
- Payment method exists on the vendor.
- GL and project accounts resolve for the target entity.
- Fiscal period exists for each accounting date.
- PO, PO line, and PO distribution resolve and agree with vendor/accounting.
- Bank and bank account exist when manual checks are imported.
- Historical payment invoice key exists, is unique, is not on hold, and has
  matching amount and currency.

---

## 9. Source-to-target mapping procedure

### Step 1: Profile the source

For each source file record:

- File name, owner, extraction query/report, extraction timestamp, and row count.
- Business grain: invoice, line, distribution, payment, or payment-invoice link.
- Null rate, distinct count, minimum/maximum, and representative values per field.
- Duplicate identities, invalid dates, nonnumeric amounts, and unexpected enums.
- Source totals by entity, vendor, fiscal period, invoice type, and status.

### Step 2: Build a mapping specification

Use one row for every source and target field:

| Source field | Source sample | Source meaning | Target column | Req | Transform/default | Validation | Reference lookup | Owner |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |

Rules:

- Target headers exactly match the current template.
- Every required, either-or, and conditional target has a source or approved constant.
- Every unmapped required field is a blocker.
- Defaults require written business approval; never invent financial values.
- Record assumptions, rejected alternatives, and unresolved questions.

### Step 3: Convert grain

For live invoices, expand:

```text
for each invoice
  for each line
    for each distribution
      output one row containing repeated header + line + distribution
```

For historical invoices, create deterministic keys:

- `invoice_key = org|vendor|vendorInvoiceNumber` or an approved stable key.
- `line_key = invoice_key|lineNumber`.
- Never use row position as a durable business key.

For historical payments, use a stable Payment Number in both sheets and an
Invoice Key already present in AP.

### Step 4: Apply explicit transforms

| Data issue | Approved transform |
| --- | --- |
| Whitespace | Trim leading/trailing whitespace; preserve meaningful internal spaces |
| Dates | Parse using documented source locale, then format for the template |
| Money | Remove display symbols/group separators; retain decimal precision; round only at approved stage |
| Boolean | Map true/yes/1/Y to `Y`; false/no/0/N to `N` |
| Invoice type | Use an approved source-code-to-target-enum crosswalk |
| Line type | Use an approved crosswalk; do not default without business approval |
| Vendor | Crosswalk source vendor to target ID/external code |
| Credit memo | Apply negative signs consistently to header, lines, and distributions |
| Action | Use `Draft` for controlled test imports; `Submit` only when workflow-ready |
| Missing distribution | Create a 100% distribution only when the GL account is known and approved |

Never truncate a value silently. Treat an overlength identifier or description
as an exception requiring correction or an approved, traceable transform.

### Step 5: Validate and reconcile

Run checks in this order:

1. File and template structure.
2. Required/either-or/conditional fields.
3. Data types, formats, enums, ranges, and lengths.
4. Cross-field formulas and date order.
5. Parent-child keys and duplicates.
6. Target reference data.
7. Source-to-output row counts, distinct counts, and financial totals.

---

## 10. Mandatory pre-import checklist

### A. Scope and source

- [ ] Import type, entity, environment, and cutover date approved
- [ ] Source extraction logic and timestamp documented
- [ ] Source file archived read-only
- [ ] Source row count, document count, and totals recorded
- [ ] Mapping and code crosswalks approved

### B. Template integrity

- [ ] Current target-instance template used
- [ ] `.xlsx`, non-empty, 30 MB or less, opens without repair
- [ ] Correct sheet count, order, names, headers, and data-start row
- [ ] No columns added, deleted, renamed, duplicated, or shifted
- [ ] No macros, external links, hidden records, merged headers, or formula errors
- [ ] Text identifiers retain leading zeros

### C. Field validation

- [ ] Required, either-or, and conditional fields populated
- [ ] Text trimmed and within limits
- [ ] Dates, numbers, integers, and booleans parse
- [ ] Enums match target-accepted values
- [ ] Percentages are 0 through 100
- [ ] Invoice/line/distribution/payment keys are unique at their scope

### D. Reconciliation

- [ ] Source records equal transformed records at the target grain
- [ ] Distinct invoice/payment counts match
- [ ] Source and output grand totals match
- [ ] Invoice headers equal line totals
- [ ] Line formulas reconcile
- [ ] Distribution percentages equal 100 and amounts equal line totals
- [ ] Credit memo signs reconcile
- [ ] Historical payment amounts and linked invoices reconcile
- [ ] Manual check groups reconcile

### E. Target references

- [ ] Org units resolve and are active
- [ ] Vendors resolve uniquely and are approved
- [ ] Vendor identifiers agree
- [ ] Remit addresses match vendors
- [ ] Payment terms and methods are active
- [ ] GL/project accounts resolve
- [ ] Accounting dates map to open/configured fiscal periods
- [ ] PO headers, lines, and distributions match
- [ ] Existing invoice duplicate check returns zero
- [ ] Historical payment invoices exist, are not on hold, and match amount/currency
- [ ] Manual banks/accounts resolve

### F. Security and approval

- [ ] Workbook is stored in an approved restricted location
- [ ] Access is limited to authorized personnel
- [ ] Sensitive bank and personal data is not placed in chat, tickets, or logs
- [ ] Independent reviewer completed validation
- [ ] Business and finance owners signed readiness result
- [ ] Import operator and planned batch window identified

---

## 11. Test import, production upload, and monitoring

1. Test with a representative batch in the designated non-production or
   controlled migration environment.
2. Include standard invoice, credit memo, PO invoice, non-PO invoice, split
   distribution, relevant tax/retainage cases, and expected failures.
3. Use `Draft` for test live invoices unless approval workflow testing is intended.
4. Download and retain the exact approved production workbook.
5. Record a checksum or immutable version identifier before upload.
6. Upload once. Do not resubmit because a job appears slow; first confirm status.
7. Record job ID, uploader, timestamp, entity, file version, and control totals.
8. Monitor until a terminal status is reached.
9. Download all result/error workbooks and retain them with the batch record.
10. Reconcile imported records before authorizing dependent imports.

For a `PARTIALSUCCESS`, do not blindly upload the original file again. Identify
successful records, create a corrections-only file for failed records, and
recheck duplicates against records already promoted.

---

## 12. Error remediation

Maintain an exception log:

| Job ID | Source key | Sheet/row | Field | Error code/message | Root cause | Correction | Owner | Retest result |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |

Classify errors before changing data:

| Category | Typical correction |
| --- | --- |
| Structural | Rebuild from current blank template |
| Required/type/enum | Correct source mapping or approved crosswalk |
| Arithmetic | Fix source amounts or transformation formula; never force a balancing plug |
| Duplicate | Remove true duplicate or resolve target/source identity |
| Reference | Correct/configure vendor, org unit, account, term, PO, or fiscal period |
| Parent-child | Correct historical keys and regenerate all dependent sheets |
| Access/system | Confirm permission/service state; do not mutate data to bypass it |

After any correction, rerun the complete validation and reconciliation suite,
not only the failed rule. Preserve the failed workbook; produce a new version.

---

## 13. Post-import reconciliation and sign-off

Complete immediately after every batch:

- Compare accepted, rejected, and total counts to the submitted workbook.
- Compare imported invoice/payment totals to source control totals.
- Recheck totals by entity, org unit, vendor, invoice type/status, fiscal period,
  payment method, and currency.
- Confirm GL/project distributions and fiscal dates.
- Confirm expected invoice statuses and workflows.
- Confirm no unintended duplicate invoices or payments were created.
- Confirm PO balances and invoice associations are correct.
- Confirm historical payment links, statuses, references, and dates.
- Confirm manual check and bank references.
- Sample records from each material category back to the source.
- Obtain business and finance sign-off.

Do not delete imported financial records to “retry” without an approved
correction/reversal process. If an import is materially wrong, stop downstream
processing, document impact, and use the product-supported void, reversal,
correction, or authorized migration-remediation procedure.

---

## 14. Data protection, audit, and retention

- AP workbooks are financial records and may contain confidential vendor,
  address, tax, bank, routing, account, and payment information.
- Use approved encrypted storage and secure transport.
- Apply least privilege and separate preparation, review, and upload duties.
- Never email unprotected bank-detail workbooks or paste sensitive values into
  logs, chat, issue trackers, or screenshots.
- Mask bank accounts and routing numbers in reports whenever full values are not required.
- Retain source extract, mapping specification, crosswalks, approved workbook,
  validation result, job ID, result/error files, exception log, reconciliation,
  and approvals according to the organization's records policy.
- Record who prepared, reviewed, approved, uploaded, corrected, and reconciled each batch.
- Do not modify or overwrite prior evidence; create a new version.

---

## 15. Reusable readiness record

```text
PRE-IMPORT VALIDATION RESULT

Import type:
Target environment/entity:
Template download date/version:
Source system and extraction timestamp:
Source file version/checksum:
Output workbook version/checksum:

Source rows:
Output rows:
Distinct invoices/payments:
Source total:
Output total:

Structural errors:
Required/type/enum errors:
Arithmetic/reconciliation errors:
Duplicate errors:
Reference-data errors:
Parent-child/link errors:
Warnings:
Warnings acknowledged by:

Prepared by/date:
Reviewed by/date:
Business approval/date:
Finance approval/date:

Result: READY FOR IMPORT | NOT READY FOR IMPORT
Reason if not ready:
```

`READY FOR IMPORT` is allowed only when every required check is verified, all
error counts are zero, and warnings are explicitly accepted by the authorized
owner.

---

## 16. Example legacy-to-live mapping

| Source | Target | Req | Transform/validation |
| --- | --- | --- | --- |
| ORG_CODE | Organization Unit* | Yes | Trim; map to active target org unit |
| VENDOR_NO | Vendor ID** | Either-or | Preserve as text; crosswalk to approved vendor |
| INV_NO | Vendor Invoice Number* | Yes | Trim; maximum 40; duplicate check |
| INV_DATE | Invoice Date* | Yes | Parse source locale; output MM/DD/YYYY |
| INV_TOTAL | Invoice Amount* | Yes | Decimal; reconcile to lines |
| Constant | Invoice Type* | Yes | `STANDARD` only when business-approved |
| Constant | Action* | Yes | `Draft` for controlled initial load |
| LINE_NO | Line #* | Yes | Integer at least 1 |
| LINE_DESC | Line Description* | Yes | Trim; nonblank |
| QTY | Quantity* | Yes | Decimal |
| UNIT_AMT | Unit Price* | Yes | Decimal |
| GL_STRING | GL Account* | Yes | Resolve against target COA |
| Constant | GL Distribution #* | Yes | `1` only for a true single distribution |
| LINE_AMT | Distribution Amount ** | Either-or | Decimal; total equals line amount |

---

## 17. Common mistakes to prevent

- Using a template from another environment or an old implementation phase.
- Treating one live row as one invoice instead of one GL distribution.
- Failing to repeat header and line fields on split-distribution rows.
- Losing leading zeros in vendor, invoice, ZIP, check, or account values.
- Filling both vendor identifiers when they point to different vendors.
- Using a vendor payment method that is not configured on that vendor.
- Supplying a PO without its PO line.
- Using inactive org units, closed/unconfigured periods, or invalid accounts.
- Mixing distribution percentages and amounts inconsistently.
- Allowing percentages to total 99.99 or 100.01 without confirming tolerance.
- Using positive credit memo lines/distributions.
- Reusing vendor invoice numbers or payment/check references.
- Truncating data silently.
- Retrying an entire partially successful batch and creating duplicates.
- Treating a technically successful job as financially reconciled.
- Sharing payment workbooks through unapproved channels.

---

## 18. Source-of-truth and limitations

This guide consolidates known NextGen AP template, batch, and shared validation
behavior. It is a preparation and preflight aid, not a replacement for the
current target-instance contract.

Use this precedence:

1. Current target-instance template for sheet structure and column order.
2. Current target runtime/batch validation behavior.
3. Approved OpenGov implementation guidance.
4. This portable guide.

When these disagree, stop, document the mismatch, and obtain confirmation before
generating or uploading data. A successful preflight reduces avoidable errors
but cannot guarantee availability of external services or prevent configuration
changes made after validation.
