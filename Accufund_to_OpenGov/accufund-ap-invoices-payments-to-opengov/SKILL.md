---
name: accufund-ap-invoices-payments-to-opengov
description: Maps AccuFund AP invoice, invoice-line, distribution, check, and payment-application data into OpenGov live or historical AP import workbooks. Use when given AccuFund database extracts and asked to choose an AP import type, build invoice/payment files, validate cross-sheet keys and amounts, or reconcile a migration.
---

# AccuFund AP Invoices and Payments to OpenGov

Self-contained mapping and validation procedure for OpenGov NextGen AP.

## Authority and safety

1. Download templates from the target OpenGov instance. Current template headers, instructions, batch YAML, and configured lookups override this skill.
2. Do not invent invoice lines, GL accounts, vendor matches, payment links, bank details, statuses, or dates.
3. Do not map API/database field names directly into a workbook unless the template uses those exact headers.
4. Preserve IDs as text. Mask bank and tax data in logs.
5. AP workbooks must be `.xlsx`, normally no larger than 30 MB. Historical imports may require OpenGov employee access.
6. Use `MM/DD/YYYY` in AP workbooks unless the downloaded template says otherwise.
7. Use decimal arithmetic, round money to 2 places only at the documented stage, and use `0.005` as the reconciliation tolerance.

## Choose the import

| Need | Import slug / type | Workbook grain |
|---|---|---|
| Current/open invoices entering AP workflow | `live-invoices` / `INVOICES_LIVE` | One flat row per GL distribution; repeat invoice and line data |
| Legacy/historical invoices, including paid history | `historical-invoices` / `HISTORICAL_INVOICES` | `invoice-header`, `invoice-lines`, `invoice-line-gl-distributions` |
| Legacy payments linked to imported invoices | `historical-payments` / `HISTORICAL_PAYMENTS` | `payments`, `payment_invoices` |

Default to historical invoices followed by historical payments when converting complete legacy history and authorized to use those imports. Use live invoices for current operational invoices. Never load the same invoice through both paths.

## AccuFund source model

Inspect schemas and profile all join keys first.

| Source | Grain / key | Purpose |
|---|---|---|
| `APinv` | Invoice header, `APINVOICEID` | Vendor, invoice number/dates, due date, description, owed/paid/balance, status |
| `APtac` | Invoice activity/line, `APACTIVITYID` | Description, quantity, unit price, amount; may be empty |
| `F9_TRX` | Posted GL line | `ACCOUNT`, `SOURCE`, `ACTIVITYDATE`, `DESCRIPTION`, `REF`, signed `AMOUNT` |
| `GLtac` | Transaction link/control | Links `APINVOICEID`, transaction, bank activity, JE, reference |
| `AFlst` | Party/vendor, `LISTID` | Name, payment terms, separate-pay flag |
| `AFadr` | Address, `ADDRESSID` | Vendor remit/primary address |
| `APbac` | Bank/check activity, `BANKACTIVITYID` | Vendor, payee, bank, check reference, amount, void/reconcile status |
| `APpac` | Invoice payment application | `BANKACTIVITYID`, `APINVOICEID`, `PAYID`, `AMOUNTPAID` |
| `APpay` | Payment run, `PAYID` | Check/payment date and first check |
| `APbnk` | Bank, `BANKID` | Bank name, account reference, routing; distinguish fields carefully |
| `AFlsu` | Optional list/document usage | Can identify department/org usage |

Profile nulls and duplicates for every join. Record any substitute table/column used in another AccuFund database.

## Shared invoice identity and normalization

- Stable historical `Invoice Key`: `text(APinv.APINVOICEID)`.
- Vendor identity: `text(APinv.LISTID)` must match the vendor import's `external_system_code*`.
- Vendor invoice number: prefer trimmed `APinv.INVOICE`; use `APINVOICEID` only as a documented fallback.
- OpenGov duplicate identity is organization unit + resolved vendor + vendor invoice number.
- Strip CR/LF from descriptions. Trim text.
- Keep ZIP and identifiers as strings.
- Resolve organization unit through an approved crosswalk; never hard-code another customer's entity name.
- Resolve GL accounts through a supplied legacy-account → OpenGov-account crosswalk. Unmapped accounts are blockers, not passthrough values, unless the target COA is proven to use the legacy string.
- Map `AFlst.APNETDAYS` to an existing target term such as `Net 30`; approved fallback only.
- Preferred remit address order after confirming types: Pay/Remit (`TYPEID 5`), Primary (`7`), Billing (`1`), Order (`4`), then `ORDER`, `ADDRESSID`.

## Build invoice distributions

Preferred source order:

1. Use genuine `APtac` lines plus their accounting distributions when complete and reconcilable.
2. Otherwise derive historical expense distributions from posted `F9_TRX`.

For `F9_TRX`, select `SOURCE='A/P'`. Link a posting to `APinv` only with a tested key. In Swatara the available natural key is:

```text
trim(F9_TRX.REF) = trim(APinv.INVOICE)
date(F9_TRX.ACTIVITYDATE) = date(APinv.ACTIVITYDATE)
trim(F9_TRX.DESCRIPTION) = trim(APinv.DESCRIPTION)
```

This key is not guaranteed unique. Count invoices per natural key:

- One invoice: assign matched distributions directly.
- Multiple invoices: allocate the combined posting by `APinv.AMOUNTOWED / sum(AMOUNTOWED)` only when this method is approved and final allocated lines tie to each invoice.
- Zero/ambiguous total or unmatched posting: block for review.

Normally positive A/P `F9_TRX.AMOUNT` rows are expense lines and negative fund/AP-liability rows are offsets. Exclude proven AP-liability offsets. If an invoice has expense-side credit/rebate rows, net those non-liability rows only under a documented rule. Never maintain an invoice-ID exception list as a portable rule.

Aggregate by invoice and legacy GL account, crosswalk the account, drop only immaterial zero rows `abs(amount) <= 0.004`, assign line numbers deterministically, and verify each invoice total.

## Historical invoices workbook

### `invoice-header`

| Target column | AccuFund mapping | Validation |
|---|---|---|
| `Invoice Key` | `text(APINVOICEID)` | Required, unique, stable across sheets |
| `Org Unit` | approved org crosswalk/constant | Active target org |
| `Invoice Type` | credit memo when source type/sign proves it; otherwise `STANDARD` | Accepted enum; credit amounts negative |
| `Inv Amt` | rounded `APinv.AMOUNTOWED` | Header equals line sum |
| `Vendor External Code` | `text(APinv.LISTID)` | Resolves vendor |
| `Vendor Name` | `AFlst.NAME` | Resolution aid; do not use as sole key |
| `Remit To Addr Line 1` | first nonblank address line | Optional/required per template |
| `Addr Line 2` | second line without duplication | Optional |
| `City` | `AFadr.CITY` | Trim |
| `State` | uppercase `AFadr.STATE` | Normally 2 characters |
| `Zip` | `AFadr.ZIPCODE` as text | Preserve leading zero |
| `Vendor Inv No` | `APinv.INVOICE`, fallback key | ≤40; unique by org+vendor |
| `Inv Date` | `APinv.INVOICEDATE` | Valid date, not future |
| `Received Date` | `APinv.ACTIVITYDATE`, fallback invoice date | ≥ invoice date, not future |
| `Accrual JE Date` | approved accounting date, often activity date | Valid fiscal period |
| `Description` | `APinv.DESCRIPTION` | Trim |
| `Payment Term` | target-resolved `AFlst.APNETDAYS` | Existing target term |
| `Payment Method` | source-confirmed method; often `CHECK` | Existing vendor method |
| `Due Date Override` | `APinv.DUEDATE` | ≥ invoice date |
| `Separate Payment Flag` | `APinv.PAYSEPARATELY`, fallback vendor flag | Accepted boolean |
| `Retainage Percent` | No standard source | Blank unless proven, 0–100 |
| `Invoice Source` | `LEGACY_IMPORT` | Accepted source |
| `Tag` | Approved migration tag | Each target-valid |
| `Status` | `INVOICESTATUS 1→PAID`, `0→APPROVED`, `2→CANCELLED`; review other codes | Accepted status; consistent with payments/balance |
| `External Inv Ref` | `APinv.INVOICE` or `REFERENCE` per project decision | Stable, ≤ target limit |

Do not replace the vendor invoice number with `APINVOICEID` silently. If duplicate source invoice numbers force a fallback, publish a crosswalk.

### `invoice-lines`

| Target column | Mapping / default | Validation |
|---|---|---|
| `Invoice Key` | Parent key | Must exist |
| `Invoice Line` | Deterministic positive sequence | Unique within invoice |
| `Line Type` | Source-derived type; `MISC`/`SERVICE` only when accepted | Valid enum |
| `Description` | AP line, invoice, or GL description | Required |
| `PO Number`, `PO Line Number` | Confirmed PO links only | PO line required when PO supplied |
| `Contract Number` | Confirmed contract only | Target-resolvable |
| `UOM` | Source UOM; blank for amount-only line | Valid target UOM |
| `Quantity` | Source quantity; otherwise `1` for amount-only line | Numeric; sign consistent |
| `Unit Price` | Source price; otherwise distribution amount | Qty × price logic |
| `Extended Amount` | Source extended amount or qty × price | Money |
| `Discount Amount`, `Freight Amount`, `Sales Tax Amount`, `Misc Charge Amount` | Source buckets only | Money; formula ties |
| `Line Subtotal` | extended − discount + freight + tax + misc | Equals distribution sum |
| `Use Tax Applicable` | Source flag, otherwise false | Boolean |
| `Use Tax Rate Pct`, `Use Tax Amount` | Source only | Rate required when applicable; 0–100 |
| `Retainage Pct`, `Retainage Amount` | Source only | 0–100; formula |
| `Net Line Amount` | Final line amount | Header sum tie |
| `External Line Reference` | `{Invoice Key}-{Invoice Line}` or true source key | Unique/stable |
| `Part Number`, `Manufacturer`, `Model`, `Serial`, `List Price` | Source item details only | Length/type limits |

### `invoice-line-gl-distributions`

| Target column | Mapping / default | Validation |
|---|---|---|
| `Invoice Key` | Parent key | Header exists |
| `Invoice Line` | Parent line number | Line exists |
| `GL Distribution No` | Positive sequence within line | Unique |
| `GL Account` | Approved crosswalk of source GL account | Exists, active, posting allowed |
| `Project Account` | Crosswalk only when source has project | Target exists |
| `PO Distribution Number` | Confirmed PO distribution only | Target resolves |
| `Percent` | `100` for a single distribution; calculated for splits | Sum exactly 100 within tolerance |
| `Amount` | Distribution amount | Sum equals line subtotal/net per template |
| `Reimbursable` | Source flag, otherwise false | Boolean |
| `External Dist Id` | `{Invoice Key}-{Line}-{Dist}` or source key | Unique/stable |

## Historical payments workbook

Load historical invoices first and use their final `Invoice Key` list as the authoritative link set.

Eligibility for each `APbac.BANKACTIVITYID`:

- `ACTIVITYTYPE='Check'` or another explicitly mapped method.
- Every `APpac` application on the payment links to an imported/existing invoice.
- Exactly one resolved vendor unless OpenGov template explicitly supports mixed-vendor payments.
- For the full-payment historical path used by this mapping, `sum(abs(APpac.AMOUNTPAID))`, sum of linked imported invoice-header amounts, and `abs(APbac.AMOUNT)` agree within `0.005`.
- Exclude unresolved mixed checks; do not drop only the bad links and import a partial payment.

If partial payments must be migrated, first confirm the current batch template's meaning for `Invoice Amount` and its allocation rules. Do not force partial applications through the full-payment eligibility rule.

### `payments`

| Target column | AccuFund mapping | Validation |
|---|---|---|
| `Vendor External Code*` | `text(APbac.LISTID)` | Resolves and agrees with linked invoices |
| `Payment Number*` | stable `LEGACY_PAY_{BANKACTIVITYID}` | Required, unique |
| `Invoice Amount*` | sum `Inv Amt` from the authoritative imported invoice headers linked by `APpac.APINVOICEID` | Reconciles to applications for full-payment path |
| `Early Pay Discount*` | Source discount, else `0` only if confirmed | Payment math |
| `Payment Amount*` | sum absolute `APpac.AMOUNTPAID`, cross-checked to `abs(APbac.AMOUNT)` | Invoice amount − discount under full-payment template semantics |
| `Payee Name` | `APbac.PAYEENAME`, fallback `AFlst.NAME` | ≤512 |
| `Payment Method*` | `CHECK`; map ACH only when `EFT` and bank details prove it | Accepted enum |
| `Remit To Addr Line 1`, `Addr Line 2`, `City`, `State`, `Zip` | Selected vendor/remit address | Length/state/ZIP validation |
| `ACH Bank Name` | Confirmed ACH bank | Required when method requires |
| `ACH Account Type` | Confirmed checking/savings | Accepted enum |
| `ACH Account Number` | Confirmed payee account | Sensitive; required for ACH |
| `ACH Routing Number` | Confirmed routing | 9 digits + ABA checksum |
| `ACH Account Holder Name` | Confirmed holder | Required per template |
| `ACH Email Address` | Confirmed notification email | Valid email |
| `Currency` | Approved constant, usually `USD` | Accepted currency |
| `Payment Reference Number` | include legacy check/ref and `BANKACTIVITYID` | ≤255; traceable |
| `Issue Date` | `APpay.CHECKDATE`, fallback `APbac.ACTIVITYDATE` | Valid date |
| `Payment Date*` | same approved payment date | Required |
| `Cleared Date` | verified clear date only | Blank unless cleared; ≥ payment date |
| `Check Bank Name` | `APbnk.BANK`/`DESCRIPTION` | Required per check rules |
| `Check Bank Account Number` | `APbnk.BANKTRANSIT` only if confirmed as bank account | Do not substitute `ROUTING` |
| `Check Number` | `APbac.REFERENCE` or `APpay.FIRSTCHECK` | Text; unique with bank identity if required |
| `Status*` | voided→`VOIDED`; reconciled→`CLEARED`; else `ISSUED` | Accepted enum and date consistency |

If check number + bank + account is duplicated, follow current importer rules. Preserve the legacy check in `Payment Reference Number`; blank or transform `Check Number` only with documented approval.

### `payment_invoices`

| Target column | Mapping | Validation |
|---|---|---|
| `Payment Number*` | Same generated payment number | Parent payment exists |
| `Invoice Key*` | `text(APpac.APINVOICEID)` | Imported/existing invoice exists; deduplicate pair |

## Live invoices

Use the downloaded `Invoice Import` sheet. The grain is one row per distribution; repeat header and line values.

Required/either-or mapping:

- `Organization Unit*` ← org crosswalk.
- `Vendor ID**` or `Vendor External System Code**` ← resolved vendor / `LISTID`.
- `Vendor Invoice Number*`, `Invoice Type*`, `Invoice Amount*`, `Invoice Date*` ← header rules above.
- `Action*` ← approved `Draft` or `Submit`; default to `Draft` when readiness is uncertain.
- `Line #*`, `Line Type*`, `Line Description*`, `Quantity*`, `Unit Price*` ← line rules.
- `GL Distribution #*`, `GL Account*`, and either `Distribution %**` or `Distribution Amount**` ← distribution rules.

Accepted common enums: invoice type `STANDARD|CREDIT_MEMO|RETAINAGE_RELEASE`; line type `ITEM|SERVICE|FREIGHT|TAX|DISCOUNT|MISC|RETAINAGE`; flags `Y|N`. Confirm against current template.

## Mandatory validations

Per invoice:

- Header, lines, and distributions join without orphans.
- Standard invoice amount > 0; credit memo amount < 0.
- Header amount = sum net line amounts within `0.005`.
- Each line has at least one distribution.
- Distribution amounts = line amount within `0.005`; percentages total 100.
- If both amount and percent exist, amount ≈ line × percent / 100; allow at most one documented penny absorber.
- Received date ≥ invoice date; due date ≥ invoice date; discount date ≤ due date; required dates not future.
- Vendor, org, payment term/method, GL, project, PO, contract, and UOM resolve in target.

Per payment:

- Payment parent unique; no orphan invoice links.
- Linked invoice vendor equals payment vendor.
- Applied sum equals payment amount under discount semantics within `0.005`.
- Method-specific fields complete; check/ACH fields are not mixed.
- Cleared status has valid cleared date; voided status follows target handling.

Cross-file:

```text
vendors imported/resolvable
→ historical invoices imported and accepted
→ historical payments linked to accepted Invoice Keys
```

## Output contract

Deliver:

1. Populated unmodified-template workbook(s).
2. Mapping manifest with source, target, transform, lookup, required status, validation, and assumption.
3. Reconciliation report: source/output counts and totals, invoice ties, orphan keys, unmapped accounts/vendors, excluded payments, and status totals.
4. Rejection file containing source keys and reasons, with sensitive values masked.

Do not declare upload-ready if any required field, referential lookup, amount tie, date rule, or cross-sheet link fails.
