---
name: incode9-ap-invoices-payments-mapping
description: Maps Incode9 AP invoice and payment CSV extracts to OpenGov NextGen live invoices, historical invoices, and historical payments. Use when APTRANF, APHEXPF, APPHISTF, APHCOMMF, APPOF, POMASTF, CHMASTF, APBANKF, APOIPF, APADDRF, or related Incode9 files are supplied.
---

# Incode9 AP invoices and payments mapping

Convert Incode9 AP extracts into the current OpenGov NextGen AP import workbooks. Preserve financial lineage, prevent join multiplication, and fail closed on unresolved target references.

## Required inputs

- Core invoices: `APTRANF.csv`.
- GL distributions: `APHEXPF.csv`.
- Payments: `APPHISTF.csv`; add `CHMASTF.csv` and `APBANKF.csv` for check/bank details.
- Optional: `APHCOMMF.csv`, `APPOF.csv`, `POMASTF.csv`, `APOIPF.csv`, `APADDRF.csv`, `APMASTF.csv`.
- Vendor crosswalk from Incode `apt_vend` to the vendor external code loaded in NextGen.
- COA crosswalk from `trim(aph_post_co) + '-' + trim(aph_acct)` to a valid NextGen accounting string.
- Organization-unit crosswalk, fiscal periods, payment terms/methods, vendors, PO references, and current target templates.

If a required source, crosswalk, target lookup, or current template is absent, produce a mapping/blocker report but do not claim import readiness.

## Preserve source grain

The legacy bronze SQL used `SELECT *`, so it is not a complete source data dictionary. Inventory the actual supplied CSV headers and data types first. Report a missing referenced column as a blocker; do not silently substitute a similarly named column.

Use these keys before any join:

| Entity | Source key |
|---|---|
| Invoice | `apt_comp + apt_vend + apt_type + apt_id` |
| Distribution | invoice key + `aph_padd` |
| Payment allocation | invoice key + `apph_padd` and payment date/check fields |
| PO link | invoice key + `appo_po` |

Deduplicate each input at its native key. Join pre-aggregated child data or generate separate output sheets; never use one wide many-to-many join. Reconcile `APTRANF.apt_gross`, summed `APHEXPF.aph_amt`, and summed payment allocations.

## Classify the output

- Open/unpaid/current invoices that must enter AP workflow → `live-invoices`.
- Legacy invoice history, including paid/voided records → `historical-invoices`.
- Payments already issued in Incode9 → `historical-payments`, loaded after historical invoice keys exist.

Do not load the same invoice through both live and historical imports. Obtain AP-owner approval for classification, statuses, invoice types, and cutover rules.

Treat `RETAINAGE_RELEASE` as `NOT READY FOR IMPORT` until the current target template and runtime explicitly confirm support.

## Common source derivations

| Derived value | Incode9 rule |
|---|---|
| `invoice_key` | Stable text such as `trim(apt_comp)|trim(apt_vend)|trim(apt_type)|trim(apt_id)`; max 64 for historical invoice headers |
| vendor external code | Vendor crosswalk using trimmed `apt_vend`; it must equal the Vendor Management import's `external_system_code` |
| source account | `trim(aph_post_co) + '-' + trim(aph_acct)` |
| NextGen accounting string | COA crosswalk lookup from the source account; never use an unverified account |
| open item / invoice date | Parse nonzero `apt_oidt` as zero-padded `MMDDYYYY` |
| due date | Parse nonzero `apt_duedt` as `MMDDYYYY` |
| discount date | Parse nonzero `apt_discdt` as `MMDDYYYY` |
| accrual/post date | Parse `apt_postdt` as `MMDDYYYY`; verify configured fiscal period |
| payment date | `MAKE_DATE(APPHISTF.yy, APPHISTF.mm, APPHISTF.dd)` |
| check number | `APPHISTF.apph_payck`, else matched `CHMASTF.chm_no` |
| cleared date | Parse nonzero `CHMASTF.chm_clear_date` as `YYYYMMDD` |
| invoice description | `APTRANF.apt_desc`; comments may append `APHCOMMF.aphcm_comm_1/2` with approved length handling |
| PO number | `APPOF.appo_po`, validated through `POMASTF.pom_po` |

Do not copy the old `fiscal_year + 1` rule blindly. NextGen resolves fiscal period from the actual accounting date.

## Historical invoice workbook

Use the target template's exact sheet positions and headers.

### Sheet 1: invoice header

| Exact NextGen header | Incode9 source | Transform / rule |
|---|---|---|
| `Invoice Key` | derived invoice key | Required when child sheets exist; unique; max 64 |
| `Org Unit` | `APTRANF.apt_comp` | Resolve through target organization-unit crosswalk |
| `Invoice Type` | `APTRANF.apt_type` | Approved crosswalk to `STANDARD`, `CREDIT_MEMO`, `DEBIT_MEMO`, `PREPAYMENT`, or `RETAINAGE_RELEASE`; never infer only from sign |
| `Inv Amt` | `APTRANF.apt_gross` | Numeric; reconcile to line and distribution totals; credit memo negative |
| `Vendor External Code` | resolved vendor crosswalk | Prefer this over name; must resolve uniquely |
| `Vendor Name` | `APMASTF.apm_name`, if supplied | Optional when external code resolves; both values must identify the same vendor |
| `Remit To Addr Line 1` | matching `APADDRF.apad_addr1`, else approved vendor remit address | Required unless status is `PAID`; must belong to vendor |
| `Addr Line 2` | `APADDRF.apad_addr2` | Max 255 |
| `City` | `APADDRF.apad_city` | Required unless `PAID`; max 100 |
| `State` | `APADDRF.apad_state` | Max 16 |
| `Zip` | `APADDRF.apad_zip` | Preserve as text; required unless `PAID`; max 16 |
| `Vendor Inv No` | `trim(apt_type) + trim(apt_id)` or approved invoice-number crosswalk | Max 40; unique for org + vendor. Do not use a renumbered value unless the crosswalk is supplied |
| `Inv Date` | parsed `apt_oidt` | Required; not future |
| `Received Date` | No deterministic 1.0 mapping | Blank unless supplied; must be between invoice date and today |
| `Accrual JE Date` | parsed `apt_postdt` | Required; must resolve to configured fiscal period |
| `Description` | `apt_desc` plus approved comments | Trim; max 10,000 |
| `Payment Term` | APTRANF/APMASTF term field if present | Resolve to active target term; do not derive from due date |
| `Payment Method` | `APMASTF.apm_eft` or payment evidence | Approved crosswalk; method must exist on vendor |
| `Due Date Override` | parsed `apt_duedt` | Blank when zero; not before invoice date |
| `Separate Payment Flag` | approved source field, if present | Boolean-compatible; otherwise blank |
| `Retainage Percent` | source retainage field, if present | 0–100; no invented value |
| `Invoice Source` | Constant | `LEGACY_IMPORT` |
| `Tag` | Optional approved migration tag | Max 100 |
| `Status` | payment/void/open facts | Approved status rule: fully paid → `PAID`; partial → `PARTIALLY_PAID`; void evidence → `VOIDED`; unpaid requires AP-owner mapping. Do not equate every record with a check to paid |
| `External Inv Ref` | invoice key or approved legacy reference | Max 255 |

### Sheet 2: invoice lines

Incode9 extracts do not expose reliable invoice item lines in the existing mapping. Use one synthetic financial line per invoice only with AP-owner approval:

| Exact NextGen header | Mapping |
|---|---|
| `Invoice Key` | derived parent key |
| `Invoice Line` | `1` |
| `Line Type` | Approved constant, normally `MISC` or `SERVICE`; no automatic default |
| `Description` | `apt_desc`, nonblank |
| `PO Number` | validated `appo_po`, if applicable |
| `PO Line Number` | Required approved PO-line lookup when PO Number is used |
| `Contract Number` | `apt_contract`, validated if populated |
| `UOM` | Blank unless supplied |
| `Quantity` | `1` |
| `Unit Price` | `apt_gross` |
| `Extended Amount` | `apt_gross` |
| `Discount Amount` | `abs(apt_disc)` only when approved and formula-consistent |
| `Freight Amount`, `Sales Tax Amount`, `Misc Charge Amount` | Blank unless separately sourced |
| `Line Subtotal` | Amount calculated under the approved line model |
| `Use Tax Applicable`, `Use Tax Rate Pct`, `Use Tax Amount` | Map only from explicit source values |
| `Retainage Pct`, `Retainage Amount` | Map only from explicit source values |
| `Net Line Amount` | Must equal the distribution basis and reconcile to header |
| `External Line Reference` | invoice key + `|1` |
| `Part Number`, `Manufacturer`, `Model`, `Serial`, `List Price` | Blank unless supplied |

If the target allows header and distributions without synthetic lines, follow the current template/runtime instead.

### Sheet 3: invoice GL distributions

One row per deduplicated `APHEXPF` record:

| Exact NextGen header | Incode9 source / rule |
|---|---|
| `Invoice Key` | parent invoice key |
| `Invoice Line` | `1` under the approved synthetic-line model |
| `GL Distribution No` | Deterministic sequence ordered by `aph_padd`; integer ≥ 1 |
| `GL Account` | COA crosswalk of `aph_post_co-aph_acct`; required |
| `Project Account` | Crosswalk of `aph_proj` + `aph_pline` when used |
| `PO Distribution Number` | Approved PO lookup only |
| `Percent` | Prefer blank when exact amount is supplied; otherwise `aph_amt / line amount * 100` |
| `Amount` | `APHEXPF.aph_amt` with sign consistent with invoice |
| `Reimbursable` | Approved source field, else false-compatible blank/default |
| `External Dist Id` | invoice key + `|` + `aph_padd`; max 255 |

Distribution amounts must total the line amount within 0.01 and percentages, when used, must total `100 ±0.01`.

## Historical payment workbook

Aggregate `APPHISTF` to one payment row per approved payment identity. Prefer a stable identity containing company, bank/check or electronic reference, and payment date. Do not merge different vendors, currencies, dates, or methods into one payment.

### `payments` sheet

| Exact NextGen header | Incode9 source | Rule |
|---|---|---|
| `Vendor External Code` | vendor crosswalk from `apph_vend` | Required; unique resolution |
| `Payment Number` | approved stable payment identity | Required; max 64; unique workbook key |
| `Invoice Amount` | Sum of positive invoice amounts linked to payment | Strictly > 0; exact linked-invoice reconciliation |
| `Early Pay Discount` | Allocated `APTRANF.apt_disc`, when supported | Required numeric ≥ 0; otherwise approved `0` |
| `Payment Amount` | Sum of absolute payment allocations | Must equal Invoice Amount − discount within 0.01 |
| `Payee Name` | `APMASTF.apm_name` or check payee source | Max 255 |
| `Payment Method` | `apm_eft`, `apph_stat`, bank/check evidence | Approved target method crosswalk; must exist on vendor |
| `Remit To Addr Line 1`, `Addr Line 2`, `City`, `State`, `Zip` | matched `APADDRF`, else approved vendor remit address | Preserve ZIP as text |
| `ACH Bank Name` | bank/EFT source if ACH | Max 255; do not use check bank automatically |
| `ACH Account Type` | `apm_eft_acct_type` if ACH | Approved enum mapping |
| `ACH Account Number` | APMASTF EFT account field, if supplied | Restricted text; max 64 |
| `ACH Routing Number` | `apm_eft_aba` if ACH | Restricted text; validate target method |
| `ACH Account Holder Name` | account-holder source, else vendor name | Max 255 |
| `ACH Email Address` | vendor EFT email, if supplied | Valid email |
| `Currency` | target/entity currency lookup | Required 3-character code; never infer when multi-currency is possible |
| `Payment Reference Number` | electronic reference or check reference | Max 255; no duplicates |
| `Issue Date` | source issue date, if distinct | Must not be after payment date |
| `Payment Date` | `yy/mm/dd` | Required; not future; payment run must resolve |
| `Cleared Date` | `chm_clear_date` | Blank when zero; not before payment date |
| `Check Bank Name` | `APBANKF.apb_name` via `apt_bank = apb_code` | Check only |
| `Check Bank Account Number` | approved bank-account lookup | Restricted text; do not substitute `apb_code` |
| `Check Number` | `apph_payck`, else `chm_no` | Check only; preserve as text; unique per target rules |
| `Status` | `CHMASTF.chm_stat`, payment status, void evidence | Approved crosswalk to `ISSUED`, `CLEARED`, or `VOIDED` |

### `payment_invoices` sheet

Emit one row per unique payment allocation:

| Header | Mapping |
|---|---|
| `Payment Number` | Exact parent payment key |
| `Invoice Key` | Exact historical `Invoice Key` already loaded |

Every payment needs at least one link; each pair must be unique. Linked invoice amounts/currency must reconcile and invoices must not be on hold.

## Live invoice mapping

Use one output row per GL distribution and repeat header/line values. Apply this column-by-column mapping:

| Exact live column | Incode9 mapping / rule |
|---|---|
| `Organization Unit*` | Organization crosswalk from `apt_comp` |
| `Vendor ID**` | Blank unless a target Vendor ID crosswalk is supplied |
| `Vendor External System Code**` | Vendor external-code crosswalk from `apt_vend`; preferred identifier |
| `Vendor Invoice Number*` | Approved source invoice number, normally `trim(apt_type)+trim(apt_id)`; max 40 |
| `Invoice Type*` | Approved `apt_type` crosswalk |
| `Invoice Amount*` | `apt_gross`; reconcile |
| `Remit To Addr Line 1` | matched `apad_addr1` or approved vendor remit address |
| `Remit To Addr Line 2` | matched `apad_addr2` |
| `Remit To City` | matched `apad_city` |
| `Remit To State` | matched `apad_state` |
| `Remit To Zip` | matched `apad_zip`, preserved as text |
| `Invoice Date*` | parsed `apt_oidt`, output `MM/DD/YYYY` |
| `Received Date` | supplied source value only; otherwise blank/default |
| `Accrual JE Date` | parsed `apt_postdt` |
| `Invoice Description` | `apt_desc` plus approved comments; max 500 |
| `Payment Term` | active target code resolved from supplied source term |
| `Payment Method` | approved crosswalk from vendor/payment evidence; must exist on vendor |
| `Bank Name` | manual/external check only; target bank lookup |
| `Bank Account Name` | manual/external check only; target account lookup |
| `Check Payee Name` | manual check payee source or approved vendor name |
| `Check Number` | `apph_payck`, else matched `chm_no`, for manual check only |
| `Check Date` | payment date for manual check; not before invoice date |
| `Check Amount` | matched `chm_amt` or reconciled payment-group amount |
| `Due Date Override` | parsed `apt_duedt` |
| `Separate Payment` | approved source field, else `N` |
| `Retainage % (Default)` | explicit retainage source only |
| `Tags` | approved migration tags, comma-separated |
| `Action*` | `Draft` for controlled loads; `Submit` only with workflow approval |
| `External Invoice Reference #` | derived invoice key |
| `Line #*` | `1` under approved synthetic-line model |
| `Line Type*` | approved constant/crosswalk; no automatic choice |
| `Line Description*` | `apt_desc`, nonblank |
| `PO #` | validated `appo_po` |
| `PO Line #` | approved PO-line lookup; required with PO |
| `Contract #` | `apt_contract`, validated |
| `Unit of Measure` | blank unless supplied |
| `Quantity*` | `1` under synthetic-line model |
| `Unit Price*` | approved calculated line amount |
| `Extended Amount` | quantity × unit price |
| `Discount Amount` | `abs(apt_disc)` only when formula-consistent |
| `Freight Amount` | explicit source value only |
| `Sales Tax Amount` | explicit source value only |
| `Misc. Charge Amount` | explicit source value only |
| `Line Subtotal` | calculated from approved component mapping |
| `Use Tax Applicable` | explicit source value; otherwise `N` |
| `Use Tax Rate %` | explicit source rate when applicable |
| `Use Tax Amount` | calculated/explicit and reconciled |
| `Line Retainage %` | explicit source value only |
| `Line Retainage Amount` | calculated/explicit and reconciled |
| `Net Line Amount` | reconciled line amount |
| `External Line Reference #` | invoice key + `|1` |
| `Part #` | blank unless supplied |
| `Manufacturer` | blank unless supplied |
| `Model` | blank unless supplied |
| `Serial #` | blank unless supplied |
| `List Price` | blank unless supplied |
| `GL Distribution #*` | deterministic sequence by `aph_padd` |
| `GL Account*` | COA crosswalk from `aph_post_co-aph_acct` |
| `Project Account` | approved project crosswalk from `aph_proj`/`aph_pline` |
| `PO Distribution #` | approved target PO-distribution lookup |
| `Distribution % **` | blank when exact amount is used; otherwise calculated |
| `Distribution Amount **` | `aph_amt`, sign/formula reconciled |
| `Reimbursable` | explicit source flag, otherwise `N` |
| `External Distribution ID` | invoice key + `|` + `aph_padd` |

The current target-generated workbook is authoritative. Preserve `Instructions`, exact 64-column order, row-2 headers, and row-3 data start.

## Validation and reconciliation

1. Workbook is nonempty `.xlsx`, at most 30 MB, exact sheets/order/headers, no hidden records or formula errors.
2. Required/either-or/conditional values pass format, enum, date, sign, and length rules.
3. No duplicate invoice identity `(Org Unit, Vendor, Vendor Inv No)` in source, workbook, or target.
4. Parent/child and payment/invoice links have no orphans.
5. Header = lines = distributions; credit signs, discount formulas, checks, and payment allocations reconcile.
6. Org, vendor, remit address, terms, methods, fiscal periods, COA/project, PO, banks, and invoice keys resolve in the target instance.
7. Record counts and totals reconcile by company, vendor, fiscal period, invoice type/status, payment method, and currency.

Return a manifest with source files/checksums, extraction timestamp, cutover rule, rows and distinct documents, source/output totals, crosswalk versions, exceptions, warnings, and `READY FOR IMPORT` or `NOT READY FOR IMPORT`.
