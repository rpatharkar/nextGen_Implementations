---
name: gp-ap-invoices-payments-mapping
description: >-
  Portable mapping and validation procedure for transforming Microsoft Dynamics
  GP AP invoices, invoice lines, GL distributions, and historical payments into
  OpenGov NextGen AP historical-invoices and historical-payments workbooks.
  Use when equivalent GP source tables are available in another project.
---

# GP AP Invoices and Payments Mapping Skill

## Purpose

Use this skill to reproduce the Sarasota Microsoft Dynamics GP to OpenGov
NextGen AP historical invoice and payment mapping outside the original
repository.

This file is self-contained. Do not assume that the Sarasota SQL, mapped
workbooks, COA crosswalk, vendor export, or payment-term workbook is present.
Request equivalent source data and reference data before transforming.

## Scope and important limitation

The proven Sarasota invoice query maps GP payables invoices with
`PM30200/PM10000/PM20000.DOCTYPE = 1` and maps GP payment documents with
`PM30200.DOCTYPE = 6`.

That is not automatically every GP AP document:

- GP `DOCTYPE = 1`: invoice
- GP `DOCTYPE = 4`: return
- GP `DOCTYPE = 5`: credit memo
- GP `DOCTYPE = 6`: payment

The current Sarasota invoice output contains only `DOCTYPE = 1` and assigns
`Invoice Type = STANDARD`. If returns or credit memos must be migrated, add them
deliberately, map them to a template-supported credit type, and make the header,
line, distribution, discount, and applied amounts consistently negative. Never
label a GP return or credit memo as `STANDARD`.

The current Sarasota payment query also exports only full-settlement cases
because it requires the sum of the linked invoices, less early-pay discount, to
equal the payment amount. It does not allocate partial payments from
`PM30300.APPLDAMT`. To migrate partial payments, first confirm that the current
OpenGov historical-payment import supports them, then define and test the
required allocation semantics; do not force partial applications through the
full-settlement formula.

The Sarasota fiscal filter starts on `2021-10-01` (FY2022) and ends on the run
date. Treat that as a project parameter, not a universal rule.

## Target imports

| Data | OpenGov slug | Batch type | Workbook sheets |
| --- | --- | --- | --- |
| Posted/legacy invoices | `historical-invoices` | `HISTORICAL_INVOICES` | `invoice-header`, `invoice-lines`, `invoice-line-gl-distributions` |
| Issued/legacy payments | `historical-payments` | `HISTORICAL_PAYMENTS` | `payments`, `payment_invoices` |

Historical imports normally require OpenGov employee access. Obtain the current
blank templates from the destination instance. If a downloaded template and
this file disagree, the downloaded template and current batch configuration win.

## Required source package

### GP invoice sources

| GP table | Required content |
| --- | --- |
| `PM30200` | Historical/open payables documents |
| `PM10000` | Unposted payables work documents |
| `PM20000` | Posted/open payables documents; include even if empty |
| `PM00200` | Vendor master and separate-payment setting |
| `PM00300` | Vendor remit addresses |
| `PM30600` | Historical payables distributions |
| `PM10100` | Work payables distributions |
| `POP30300` | Posted purchasing receipts linking receipt to voucher |
| `POP10500` | Receipt-match/PO invoice lines |
| `POP30310` | Posted receipt line descriptions and UOM |
| `IV00101` | Item descriptions |
| `GL00100` | Account index to legacy account string |

### Additional GP payment sources

| GP table | Required content |
| --- | --- |
| `PM30300` | Payment-to-invoice application rows |
| `CM00100` | Checkbook, bank, and account number |
| `CM20200` | Bank reconciliation, clearing, and void state |
| `CM20202` | Historical EFT/ACH transaction snapshot |
| `SY06000` | Vendor EFT account type |

### Destination/reference data

Require these destination-specific references:

1. Current OpenGov historical invoice and historical payment templates.
2. GP account string to active OpenGov GL account crosswalk.
3. OpenGov vendor export containing external system code, approval status,
   legal name, remit address, and enabled payment methods.
4. OpenGov payment-term lookup containing code and exact configured name.
5. OpenGov organization-unit lookup.
6. Existing target invoice keys and vendor invoice identities when importing
   into an instance that already contains AP history.
7. Valid target payment runs or accepted payment-date periods.

Do not assume GP IDs are OpenGov internal IDs. Prefer the GP `VENDORID` as the
OpenGov vendor external system code when that is how vendors were imported.

## Global transform conventions

- Trim all identifiers and text used in joins.
- Keep voucher, vendor, payment, check, PO, account, routing, and bank account
  values as text so leading zeros are preserved.
- Write dates as real Excel dates displayed `MM/DD/YYYY`.
- Write money at two decimal places. Use a half-cent comparison tolerance of
  `0.005`.
- Use a unit-price comparison tolerance of `0.01`.
- Convert blank strings to null unless the template explicitly requires text.
- Convert booleans to the exact representation accepted by the current
  historical template. Sarasota writes Excel booleans for historical invoices.
- Never truncate a key to make it fit. Stop and report the offending values.
- Never fabricate a vendor, GL account, PO, invoice link, payment method, bank
  detail, or remit address.
- Use fail-closed selection: invalid records go to an exclusions report and
  never to the upload workbook.

## Invoice extraction and identity

Create a normalized invoice-header source from `PM30200`, `PM10000`, and
`PM20000`.

For the proven STANDARD-invoice path:

1. Filter `DOCTYPE = 1`.
2. Require nonblank `VCHRNMBR` and `VENDORID`.
3. Require a valid `DOCDATE` inside the project date window and not in the
   future.
4. Exclude amounts with `abs(DOCAMNT) < 0.005`; a STANDARD invoice must be
   strictly positive.
5. Deduplicate by trimmed `VCHRNMBR + VENDORID`, preferring `PM30200`, then
   `PM10000`, then `PM20000`; use stable row ordering such as `DEX_ROW_ID`.
6. Set `Invoice Key = trim(VCHRNMBR)`.

Before relying on `VCHRNMBR` alone, prove that it is globally unique across the
selected company and date scope. If it is not, use a deterministic key such as
`company|vendor|voucher` consistently across all sheets and payment links,
subject to the target template's key length.

## Historical invoice field mapping

The exact Sarasota headers below match the mapped workbook. Preserve the
template's spelling and column order.

### Sheet: `invoice-header`

One row per invoice key.

| Target column | GP source / transform | Validation |
| --- | --- | --- |
| `Invoice Key` | Trimmed `VCHRNMBR` | Required; unique; stable across all sheets |
| `Org Unit` | Sarasota literal `Primary Government`; otherwise resolve from the first purchase distribution's crosswalked GL account or an approved business rule | Required; must exist and be active |
| `Invoice Type` | Sarasota `STANDARD` for `DOCTYPE=1`; map supported credit documents explicitly | Required; accepted enum; sign must agree |
| `Inv Amt` | `round(DOCAMNT, 2)` | Required; nonzero; equals sum of net lines |
| `Vendor External Code` | Trimmed `VENDORID` | Required for this profile; must resolve uniquely to an approved target vendor |
| `Vendor Name` | `PM00200.VENDNAME`, fallback to `VENDORID` | Resolution aid; do not use as the primary key |
| `Remit To Addr Line 1` | Prefer `PM00300` row matching `VADCDTRO`, then `PRIMARY`, then `PM00200`; promote `ADDRESS2` when `ADDRESS1` is blank | If populated, must match a target vendor remit address |
| `Addr Line 2` | `ADDRESS2`, but blank when it was promoted to line 1 | Same remit-address tuple |
| `City` | Selected remit row `CITY` | Same remit-address tuple |
| `State` | Uppercase two-character state code | Same remit-address tuple |
| `Zip` | Selected remit row `ZIPCODE`, retained as text | Same remit-address tuple |
| `Vendor Inv No` | Trimmed `DOCNUMBR` | Required; max 40; unique by org unit + vendor |
| `Inv Date` | `DOCDATE` | Required; valid date; not future |
| `Received Date` | `InvoiceReceiptDate`; if null, invalid/1900, or before invoice date, use invoice date | Must be on/after invoice date and not future |
| `Accrual JE Date` | Greatest valid date among `PSTGDATE`, `POSTEDDT`, and invoice date | Must not precede invoice date; must map to a valid fiscal period |
| `Description` | `LNGDESC`, fallback `TRXDSCRN` | Trim; preserve meaningful text |
| `Payment Term` | Map `PYMTRMID` to exact OpenGov term name; fallback only to a business-approved vendor/default term | Must exist in destination if populated |
| `Payment Method` | Sarasota: `ACH` when `Electronic <> 0`; otherwise blank so vendor default applies | If populated, exact enabled vendor method |
| `Due Date Override` | Valid `DUEDATE`; convert 1900 sentinel to null | Must be on/after invoice date |
| `Separate Payment Flag` | `PM00200.ONEPAYPERVENDINV <> 0` | Boolean |
| `Retainage Percent` | `100 * RETNAGAM / DOCAMNT` when amount is nonzero | Range 0–100; consistent with retainage amount |
| `Invoice Source` | Literal `IMPORT` | Must be accepted by current template |
| `Tag` | Sarasota fiscal year, where Oct–Dec belongs to next FY | Each tag at most 50 characters |
| `Status` | `VOIDED` if voided; `PAID` if `abs(CURTRXAM)<0.005`; `APPROVED` if current amount equals document amount; otherwise `PARTIAL` | Must be accepted by historical template |
| `External Inv Ref` | Invoice key | Optional audit key; max 255 |

Sarasota payment-term normalization:

| GP value | Lookup code |
| --- | --- |
| `Net 30`, `Net 15`, `Net 20`, `Net 25`, `Net 10`, `Net 14`, `Net 21`, `Net 45` | `NET30`, `NET15`, `NET20`, `NET25`, `NET10`, `NET14`, `NET21`, `NET45` |
| `Due Upon Receipt` | `RECEIPT` |
| `Credit Card` | `CREDIT_CARD` |
| `1% 15/Net 30` | `DISC1_15_NET30` |
| `2% 10/Net 30` | `DISC2_10_NET30` |
| `2% 20/Net 30` | `DISC2_20_NET30` |
| `2% 25/Net 30` | `DISC2_25_NET30` |
| `Net 10th`, `Net 10th Prox`, `Net 15th`, `Net 25th` | `NET10TH`, `NET10TH_PROX`, `NET15TH`, `NET25TH` |
| Blank | Sarasota fallback `NET30`; replace with destination-approved policy |

Resolve the lookup code to the exact OpenGov payment-term **name**. Do not write
the code unless the current template explicitly requests the code.

### Sheet: `invoice-lines`

One or more rows per invoice key. `Invoice Line` is a positive integer unique
within the invoice.

PO-matched strategy:

1. Join `POP30300` to `POP10500` by receipt number and vendor, then to the
   normalized invoice header by voucher and vendor.
2. Number lines deterministically by receipt, receipt line, PO line, and source
   row ID.
3. Use `ITEM` when `ITEMNMBR` is nonblank, otherwise `SERVICE`.
4. Description preference: `POP30310.ITEMDESC`, `IV00101.ITEMDESC`,
   `ITEMNMBR`, invoice description, then `PO invoice line`.
5. Quantity is the greatest usable value from `QTYINVCD`, `UMQTYINB`, and zero.
6. Extended amount prefers nonzero `Total_Landed_Cost_Amount`, then `OREXTCST`.
7. Unit price is extended amount divided by quantity when quantity is nonzero;
   otherwise use `OLDCUCST`.

Non-PO strategy:

- Create one synthetic `SERVICE` line.
- Quantity = `1`.
- Unit/extended amount = purchase amount.
- Populate discount, freight, tax, miscellaneous, and retainage from the header.
- Net line amount = document amount.

| Target column | GP source / transform | Validation |
| --- | --- | --- |
| `Invoice Key` | Parent normalized invoice key | Required; parent header must exist |
| `Invoice Line` | Deterministic row number, starting at 1 | Required; positive and unique within invoice |
| `Line Type` | `ITEM` or `SERVICE` by strategy | Required; accepted enum |
| `Description` | Description preference above | Required; nonblank |
| `PO Number` | Sarasota leaves blank to avoid target `PO_NOT_FOUND` | If used, PO must exist in target |
| `PO Line Number` | Sarasota leaves blank | Required when PO Number is supplied |
| `Contract Number` | Blank unless a verified target contract mapping exists | Must resolve if populated |
| `UOM` | `POP30310/POP10500.UOFM` | Max 64; target-compatible abbreviation/name |
| `Quantity` | PO quantity or synthetic 1 | Required for quantity-based line; valid range |
| `Unit Price` | Derived price above | Required for quantity-based line; math must reconcile |
| `Extended Amount` | Rounded source extended amount | Quantity × unit price within tolerance |
| `Discount Amount` | Header `TRDISAMT` for synthetic line; zero in Sarasota PO lines | Numeric; included in formula |
| `Freight Amount` | Header `FRTAMNT` for synthetic line; otherwise approved allocation | Numeric |
| `Sales Tax Amount` | Header `TAXAMNT` for synthetic line; otherwise approved allocation | Numeric |
| `Misc Charge Amount` | Header `MSCCHAMT` for synthetic line; otherwise approved allocation | Numeric |
| `Line Subtotal` | Extended − discount + freight + tax + misc, or proven source total | Required semantically; reconciles to distributions |
| `Use Tax Applicable` | Sarasota `false` | If true, rate is required |
| `Use Tax Rate Pct` | Null unless use tax is applicable | Range 0–100 |
| `Use Tax Amount` | Sarasota zero | Must agree with rate/base if used |
| `Retainage Pct` | Header-derived percent for synthetic line; otherwise approved line source | Range 0–100 |
| `Retainage Amount` | Header `RETNAGAM` for synthetic line | Must agree with percent/base |
| `Net Line Amount` | Proven final line amount | Sum across lines must equal header |
| `External Line Reference` | Prefer original PO number; otherwise receipt/source line key | Max 255; audit-only |
| `Part Number` | `ITEMNMBR` | Max 128 |
| `Manufacturer` | Blank unless sourced | Max 255 |
| `Model` | Blank unless sourced | Max 128 |
| `Serial` | Blank unless sourced | Max 128 |
| `List Price` | `OLDCUCST`, or synthetic unit price | Numeric |

If an invoice has exactly one line and its source line total does not equal
`DOCAMNT`, Sarasota rebuilds that line from `DOCAMNT`. Do not automatically
spread a difference across multiple lines. Exclude multi-line mismatches for
business review unless an authoritative allocation rule is supplied.

### Sheet: `invoice-line-gl-distributions`

Use purchase distributions from `PM30600` and `PM10100` where:

- invoice path uses `DISTTYPE = 6`;
- work distributions also use `CNTRLTYP = 0`;
- amount = `DEBITAMT - CRDTAMNT`;
- source precedence favors history over work;
- duplicate distribution sequence rows are removed.

For voided GP vouchers, reversal rows can wash original distributions to zero.
The Sarasota logic pairs equal opposite amounts by voucher, vendor, account
index, and absolute amount, then removes the newest reversing pairs.

Link a distribution to a PO line when `DSTINDX = INVINDX`; otherwise use the
approved fallback line. If a PO line has `INVINDX` but no purchase distribution,
create one line-level distribution for its net amount. Do not upload placeholder
distributions with a null GL account.

| Target column | GP source / transform | Validation |
| --- | --- | --- |
| `Invoice Key` | Parent key | Required; header exists |
| `Invoice Line` | Matched line number | Required; line exists |
| `GL Distribution No` | Deterministic row number per invoice line | Required; integer >= 1 and unique within line |
| `GL Account` | `GL00100.ACTNUMBR_1-2-3`, replaced by active OpenGov COA crosswalk | Required; must resolve in target entity |
| `Project Account` | Blank unless verified crosswalk exists | Must resolve if populated |
| `PO Distribution Number` | Blank in Sarasota | Must resolve if populated |
| `Percent` | `100 * abs(distribution amount) / sum(abs(amount))` by line | Either percent or amount required; percent total 100 |
| `Amount` | Rounded `DEBITAMT - CRDTAMNT` | Either amount or percent required; amount total equals line |
| `Reimbursable` | Sarasota `false` | Valid boolean |
| `External Dist Id` | Source `DSTSQNUM` or stable line fallback | Stable audit key |

When both percent and amount are supplied, both sets of math must pass. A safer
portable default is to supply exact distribution amounts and either omit
percent, if the template permits, or calculate percentages and assign the final
rounding remainder to one row.

## Historical payment mapping

Load historical invoices first. Payment links depend on their `Invoice Key`.

### Payment eligibility

Create payment headers from `PM30200` where `DOCTYPE = 6`, deduplicated by
payment voucher number using the newest stable source row.

Create apply rows from `PM30300` where:

- payment document `DOCTYPE = 6`;
- applied-to document type is in `(1, 4, 5)`;
- payment voucher and applied voucher are nonblank.

For each payment, export only when every condition passes:

1. Every source apply row is in the mapped invoice scope.
2. No duplicate payment/invoice pair exists.
3. All linked invoices resolve to exactly one vendor.
4. Payment vendor equals linked invoice vendor.
5. Target vendor exists and is `APPROVED`.
6. Payment entry type is supported: Sarasota `0 = Check`, `3 = ACH`.
7. Payment amount is strictly positive.
8. Payment date exists and is not in the future.
9. `linked invoice amount - early pay discount = payment amount` within `0.005`.
10. Discount is nonnegative.
11. Write-off total is zero within `0.005`; the current template cannot
    represent a write-off.
12. Source invoices exist and are not on hold.
13. Linked invoice statuses are not `VOIDED`, `CANCELLED`, or `REJECTED`.
14. All linked invoices and the payment use one matching currency; Sarasota
    requires `USD`.
15. Check payments have check number, bank name, and bank account number.
16. Nonblank check numbers are unique in the export.

This fail-closed rule means a payment is excluded if even one linked invoice was
outside the invoice date window or omitted from the invoice workbook.

### Sheet: `payments`

One row per payment.

| Target column | GP source / transform | Validation |
| --- | --- | --- |
| `Vendor External Code*` | Vendor code from linked mapped invoices; verify against payment `VENDORID` | Required; one approved vendor |
| `Payment Number*` | Trimmed payment `VCHRNMBR` | Required; unique; text max 64 |
| `Invoice Amount*` | Sum of linked mapped invoice amounts | Required; agrees with links |
| `Early Pay Discount*` | Sum `PM30300.DISTKNAM` | Required; >= 0 |
| `Payment Amount*` | Payment header `DOCAMNT` | Required; > 0; invoice amount − discount |
| `Payee Name` | `VNDCHKNM`, fallback target vendor legal name | Optional |
| `Payment Method*` | Entry type 0 → `Check`; 3 → `ACH` | Required; accepted and enabled |
| `Remit To Addr Line 1` | Target vendor export remit tuple | If populated, must match vendor |
| `Addr Line 2` | Target vendor export remit tuple | Same |
| `City` | Target vendor export remit tuple | Same |
| `State` | Target vendor export remit tuple | Two-character code |
| `Zip` | Target vendor export remit tuple | Preserve as text |
| `ACH Bank Name` | `CM20202.BANKNAME` for ACH | Method-conditional |
| `ACH Account Type` | `SY06000.EFTAccountType`: 1 Checking, 2 Savings, 3 General Ledger, 4 Loan | Method-conditional; accepted enum |
| `ACH Account Number` | `CM20202.EFTBankAcct` | Method-conditional; preserve as text |
| `ACH Routing Number` | `CM20202.EFTTransitRoutingNo` | Method-conditional; preserve leading zeros |
| `ACH Account Holder Name` | `CM20202.paidtorcvdfrom` | Method-conditional |
| `ACH Email Address` | Blank unless authoritative source exists | Valid email if populated |
| `Currency` | Normalize `Z-US$`, `USD`, `US$` to `USD` | Must match all linked invoices |
| `Payment Reference Number` | Blank in Sarasota unless authoritative unique reference exists | Unique when populated |
| `Issue Date` | Payment `DOCDATE` | Must not be after Payment Date |
| `Payment Date*` | Payment `DOCDATE` | Required; not future; accepted target run/period |
| `Cleared Date` | Max valid `CM20200.clearedate` for payment + checkbook | Must be on/after Payment Date |
| `Check Bank Name` | `CM00100.BANKID` for Check | Required by Sarasota eligibility for Check |
| `Check Bank Account Number` | `CM00100.DDACTNUM`, fallback `BNKACTNM`, for Check | Required by Sarasota eligibility for Check |
| `Check Number` | Payment `DOCNUMBR` for Check | Required for Check; unique when nonblank |
| `Status*` | `VOIDED` if AP or CM voided; else `CLEARED` if cleared date exists; else `ISSUED` | Required; accepted enum |

The downloaded historical-payment template marks required columns with `*` for
documentation. Before upload, remove every `*` from both data-sheet header rows
and delete the `Instructions` sheet. The importer expects only `payments` and
`payment_invoices`, in that order, with unstarred headers. The Sarasota mapped
payment workbook follows this upload-ready convention.

### Sheet: `payment_invoices`

One row per unique payment/invoice relationship.

| Target column | GP source / transform | Validation |
| --- | --- | --- |
| `Payment Number*` | `PM30300.VCHRNMBR` | Required; max 64; parent payment exists |
| `Invoice Key*` | `PM30300.APTVCHNM` | Required; max 100; target invoice exists uniquely |

Do not aggregate away the relationship sheet. The sum of linked invoice amounts
must equal the payment row's `Invoice Amount`.

## Validation procedure

Run every section in order. Stop workbook generation on any hard failure.

### Gate 0 — Template and file

- [ ] Current template downloaded from the destination instance.
- [ ] Sheet names, header spelling, and header order match the current template.
- [ ] Historical-payment upload headers have their documentation `*` markers
      removed and the `Instructions` sheet has been deleted.
- [ ] Output is `.xlsx`, not CSV or old `.xls`.
- [ ] File size is at most 30 MB.
- [ ] No hidden extra data rows, merged data cells, formulas with stale cached
      values, or instructions copied into data sheets.
- [ ] Identifiers remain text and dates are displayed `MM/DD/YYYY`.

### Gate 1 — Source completeness

- [ ] All required GP tables are present or the missing table has a documented,
      business-approved fallback.
- [ ] Company/database identity and extraction timestamp are recorded.
- [ ] Date and company scope are explicit.
- [ ] GP row counts and control totals are recorded before transformation.
- [ ] Duplicate source rows and source-table precedence are deterministic.
- [ ] COA, vendor, org-unit, payment-term, and target-invoice references are
      current for the destination instance.

### Gate 2 — Invoice structure and required values

- [ ] Every `Invoice Key` is unique on `invoice-header`.
- [ ] Every line has exactly one parent header.
- [ ] Every distribution has exactly one parent line.
- [ ] Every invoice has at least one line.
- [ ] Every line has at least one valid GL distribution.
- [ ] Invoice line and distribution numbers are positive integers and unique
      within their parent.
- [ ] Org unit, invoice type, invoice amount, vendor external code, vendor
      invoice number, invoice date, received date, accrual date, and status are
      populated as required by the current historical template.
- [ ] Line type and description are populated.
- [ ] GL account is populated.
- [ ] PO line is populated whenever a PO number is sent.
- [ ] Use-tax rate is populated whenever use tax is true.
- [ ] Each distribution has amount or percent.

### Gate 3 — Formats, enums, lengths, and ranges

- [ ] Invoice types are accepted by the current batch. Common values include
      `STANDARD`, `CREDIT_MEMO`, and `RETAINAGE_RELEASE`.
- [ ] STANDARD amounts are strictly positive; CREDIT_MEMO amounts are strictly
      negative at header, line, and distribution levels.
- [ ] Line types are accepted: `ITEM`, `SERVICE`, `FREIGHT`, `TAX`, `DISCOUNT`,
      `MISC`, or `RETAINAGE`.
- [ ] Payment methods and statuses exactly match the current template.
- [ ] Vendor invoice number is at most 40 characters.
- [ ] Tag is at most 50 characters.
- [ ] Invoice/external references are at most 255 characters.
- [ ] PO number and UOM are at most 64 characters.
- [ ] Part number is at most 128; manufacturer 255; model and serial 128.
- [ ] Quantity is between `0.0001` and `999,999,999` when quantity-based.
- [ ] Unit price is between `0.0001` and `999,999,999.99` when required.
- [ ] Monetary line values are between `-999,999,999.99` and
      `999,999,999.99`.
- [ ] Retainage and use-tax percentages are between 0 and 100.

### Gate 4 — Invoice arithmetic

For each invoice:

- [ ] `Inv Amt = sum(Net Line Amount)` within `0.005`.
- [ ] Discount line semantics follow the current batch; discount lines subtract
      the absolute subtotal.

For each line:

- [ ] `Extended Amount = Quantity * Unit Price` within allowed tolerance when
      no authoritative override applies.
- [ ] `Line Subtotal = Extended - Discount + Freight + Sales Tax + Misc`
      according to the destination product formula.
- [ ] `sum(distribution Amount) = Line Subtotal/accepted line amount` within
      `0.005`.
- [ ] `sum(distribution Percent) = 100` when percent is supplied.
- [ ] When both amount and percent are supplied, each amount equals
      `line amount * percent / 100`, allowing only the documented penny
      remainder.

Reconcile transformed invoice count and total against the eligible source set.
Record exclusions by reason. Do not compare only workbook grand totals; also
compare by fiscal year, vendor, invoice type, and status.

### Gate 5 — Invoice dates and uniqueness

- [ ] Invoice Date is not future.
- [ ] Received Date is on/after Invoice Date and not future.
- [ ] Accrual JE Date is not before Invoice Date and maps to a valid target
      fiscal period.
- [ ] Due Date Override is on/after Invoice Date.
- [ ] Discount date, if used, is on/before due date.
- [ ] No duplicate `Org Unit + resolved Vendor + Vendor Inv No` exists inside
      the workbook.
- [ ] The same invoice identity does not already exist in target AP.

### Gate 6 — Destination lookups (L3)

- [ ] Every org unit exists and is active.
- [ ] Every vendor external code resolves uniquely to an approved vendor.
- [ ] Every supplied remit-address tuple matches that vendor in OpenGov.
- [ ] Every supplied payment term exists by exact configured name.
- [ ] Every supplied payment method is enabled for the resolved vendor.
- [ ] Every GL account is active in the destination entity and valid for the
      accounting date.
- [ ] Every project account, PO, PO line, contract, and PO distribution supplied
      in the workbook resolves in the destination.

These checks cannot be proven from GP extracts alone.

### Gate 7 — Payments

- [ ] Required starred payment fields are populated.
- [ ] Payment Number is unique.
- [ ] Payment Number + Invoice Key pairs are unique.
- [ ] Every payment has at least one invoice link.
- [ ] No payment-invoice row is orphaned.
- [ ] Every Invoice Key exists uniquely in target AP, has expected vendor,
      amount, currency, status, and hold state.
- [ ] Payment Amount = Invoice Amount − Early Pay Discount within `0.005`.
- [ ] Payment row Invoice Amount = sum of amounts for linked Invoice Keys.
- [ ] No unsupported write-off remains.
- [ ] Currency is consistent; apply the destination's accepted currency list.
- [ ] Payment Date is not future.
- [ ] Issue Date is not after Payment Date.
- [ ] Cleared Date is not before Payment Date.
- [ ] Status is accepted; Sarasota uses `ISSUED`, `CLEARED`, `VOIDED`.
- [ ] Nonblank check numbers are unique.
- [ ] Nonblank payment reference numbers are unique.
- [ ] ACH rows have complete, valid ACH details; Check rows have complete check
      bank/account/number details.
- [ ] Each vendor has the selected payment method active.
- [ ] Every Payment Date resolves to an accepted target payment run or period.

## Mandatory outputs

Produce all of the following for each run:

1. Historical invoice workbook with the three exact template sheets.
2. Historical payment workbook with `payments` and `payment_invoices`.
3. Invoice exclusions file with source key and every exclusion reason.
4. Payment exclusions file with payment number and every exclusion reason.
5. Validation report containing each check, error count, `PASS/FAIL`, and sample
   failing keys.
6. Readiness report for destination-only checks marked `PASS`, `FAIL`, or
   `UNVERIFIED`.
7. Reconciliation report showing source, eligible, exported, and excluded row
   counts and monetary totals.
8. Run manifest with source company, extraction timestamp, date scope, template
   version/date, transform version, and hashes of generated workbooks.

No workbook is upload-ready while a required check is `FAIL` or a mandatory
destination lookup remains `UNVERIFIED`.

## Safe execution order

1. Inventory source tables and profile keys, nulls, date ranges, and amounts.
2. Load current OpenGov templates and destination reference exports.
3. Build and validate invoice headers.
4. Build invoice lines and distributions.
5. Run invoice structural, arithmetic, uniqueness, and destination checks.
6. Generate and dry-run the historical invoice workbook.
7. Resolve all invoice import errors and confirm imported Invoice Keys.
8. Build payment/apply rows against the final imported invoice population.
9. Run payment eligibility, arithmetic, method, date, and destination checks.
10. Generate and dry-run the historical payment workbook.
11. Archive result/error workbooks and the run manifest.

## Hard rules for an agent using this skill

1. Never invent target headers; inspect the current templates.
2. Never silently omit a GP table, document type, date range, or excluded row.
3. Never call the current `DOCTYPE=1` Sarasota mapping “all AP documents.”
4. Never create a payment whose complete source invoice-link set is not mapped.
5. Never use a legacy GL account without proving it exists in the destination.
6. Never populate a remit address unless it matches the target vendor record.
7. Never treat a vendor external code as an OpenGov internal vendor ID.
8. Never upload placeholder distributions, null GL accounts, zero STANDARD
   invoices, unresolved keys, or unreconciled totals.
9. Never change signs merely to make totals balance; determine document
   semantics first.
10. Prefer `Draft` for live-invoice dry runs, but do not add live-invoice-only
    fields to historical templates.
11. Preserve evidence: every exclusion and default must be reported.
12. When template instructions, batch errors, and this file disagree, the
    current destination template/batch behavior is authoritative; document and
    update the mapping rule.
