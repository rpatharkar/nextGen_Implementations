---
name: accufund-vendors-to-opengov
description: Maps AccuFund vendor, address, contact, tax, and payment-method database extracts into the OpenGov Vendor Bulk Import workbook. Use when given AccuFund tables, Parquet/CSV exports, or an OpenGov vendor template and asked to build, validate, reconcile, or explain a vendor migration.
---

# AccuFund Vendors to OpenGov

Portable mapping contract for transforming AccuFund vendor data into the OpenGov Vendor Bulk Import workbook.

## Non-negotiable rules

1. Download the current blank OpenGov template from the target instance. Its sheet names, headers, instructions, enums, and required markers override this skill.
2. Never invent missing tax IDs, contacts, addresses, certificates, category codes, or bank details.
3. Treat identifiers, tax IDs, ZIP codes, phone numbers, account numbers, and routing numbers as text. Preserve leading zeroes.
4. Do not log or display full TIN, SSN, bank account, or routing values. Mask them in reports.
5. Keep the workbook format and sheet names unchanged. Do not add columns.
6. A trailing `*` in a template header means required.
7. Use one stable `vendor_import_key*` on every child sheet. Default to trimmed `AFlst.LISTID`.
8. Fail the mapping when a required value is missing; do not replace it with fake data.

## Expected AccuFund sources

Discover tables case-insensitively and inspect their schemas before mapping:

| Source | Grain / key | Relevant columns |
|---|---|---|
| `AFlst` | One party, `LISTID` | `USEVENDOR`, `NAME`, `NNAME`, `FNAME`, `LNAME`, `EMAIL`, `TID`, `USEINDIVIDUAL`, `IS1099`, `APNETDAYS`, `PAYSEPARATELY`, `INACTIVE` |
| `APinv` | One AP invoice, `APINVOICEID` | `LISTID`; proves a payee was used by AP |
| `AFadr` | One address, `ADDRESSID` | `LISTID`, `TYPEID`, `ORDER`, `STREET1`, `STREET2`, `CITY`, `STATE`, `ZIPCODE`, `COUNTRY` |
| `AFphn` | One phone, `PHONEID` | `LISTID`, `CONTACTID`, `TYPEID`, `ORDER`, `AREACODE`, `PHONENUMBER`, `EXTENSION` |
| `AFtyp` | Type lookup, `TYPEID` | `LOCATION`, `TYPE`, `DESCRIPTION` |
| `AFcon` | One contact, `CONTACTID` | `LISTID`, names, `TITLE`, `EMAIL`, `INACTIVE` |
| `AFeft` | One EFT instruction, `EFTREQUESTID` | `LISTID`, `ORDER`, `EFTTYPE`, `ACCOUNTTYPE`, `BANKDFI`, `BANKACCOUNT` |
| `AFnot` | Optional party notes | Do not map to a template field unless the current template supplies one |

If equivalent data arrives under different names, map by meaning and record the substitution. Produce a source-schema report with table, column, type, null count, distinct count, and sample values (sensitive values masked).

## Vendor population and grain

Include a party when:

```text
coalesce(AFlst.USEVENDOR, 0) = 1
OR AFlst.LISTID occurs in APinv.LISTID
```

This includes AP payees such as employee reimbursements that were not flagged as vendors. Output exactly one `vendors` row per `LISTID`. Before writing, report duplicate `LISTID`, blank `NAME`, blank `TID`, and duplicate normalized TIN separately.

## Global normalization

- Trim strings; convert placeholders (`NULL`, `N/A`, `#N/A`, `-`) to blank only when they are placeholders, not legitimate codes.
- Booleans: emit the values accepted by the current template; use `TRUE`/`FALSE` when no instruction is supplied.
- Dates: use the template's required workbook format, normally `MM/DD/YYYY`.
- Email: trim and lowercase for comparison; retain original casing if desired. Validate one `@`, nonblank local/domain parts, and no spaces.
- Phone/fax: concatenate usable `AREACODE` and `PHONENUMBER`, remove non-digits, remove one leading US country digit only when the result has 11 digits and starts with `1`; emit `+1` separately. A US national number must have 10 digits.
- TIN: remove spaces and hyphens for validation. Require 9 digits for EIN/SSN unless the current template explicitly allows another format. Use `FTIN` only when a foreign tax identifier and its supporting classification are actually supplied.
- Routing number: digits only, left-pad only when source metadata proves leading zeroes were lost, require 9 digits, and validate the ABA checksum.
- Never numerically coerce identifiers.

## Sheet `vendors`

| OpenGov column | AccuFund mapping | Validation |
|---|---|---|
| `vendor_import_key*` | `text(AFlst.LISTID)` | Required, unique, stable; must match every child row |
| `legal_company_name*` | `trim(AFlst.NAME)` | Required; one row per key |
| `doing_business_as` | `trim(AFlst.NNAME)` | Blank when absent; do not duplicate legal name unless requested |
| `phone_country_code` | `+1` when a valid selected phone exists | Blank if phone blank |
| `phone_number` | Best normalized non-fax `AFphn` phone | 10 US digits; no punctuation |
| `phone_ext` | Selected `AFphn.EXTENSION` when > 0 | Digits only |
| `email` | `trim(AFlst.EMAIL)` | Valid email or blank |
| `company_website` | No standard source | Blank unless supplied |
| `business_type` | No confirmed standard source | Blank or target-approved enum such as Sole Proprietorship/LLC; never infer from the name |
| `is_1099_applicable` | `AFlst.IS1099=1` | Boolean |
| `state_of_incorporation` | Selected address `STATE`; optional project default only with approval | Valid target state value; do not assume state merely because address exists |
| `tax_type*` | `SSN` if `USEINDIVIDUAL=1`, otherwise `EIN`; use `FTIN` only from proven foreign-tax data | Required; accepted enum; verify ambiguous entities |
| `tax_id*` | `trim(AFlst.TID)` | Required by template; 9 normalized digits; secure handling |
| `payment_term*` | `Net {APNETDAYS}`; use `Net 30` only under an approved default | Must exist in target OpenGov |
| `is_separate_payment` | `PAYSEPARATELY=1` | Boolean |
| `company_description` | No reliable standard source | Blank unless supplied |
| `fax_country_code` | `+1` when valid fax exists | Blank with blank fax |
| `fax_number` | Normalized `AFphn` where fax type | 10 US digits |
| `fax_ext` | Fax `EXTENSION` when > 0 | Digits only |
| `external_system_code*` | `text(AFlst.LISTID)` | Required and unique in target vendor domain |
| `local_profiles` | No confirmed standard source | Blank or target-approved value |
| `is_one_time_vendor` | Default `FALSE` only if migration policy confirms | Boolean |
| `vendor_type` | Project constant such as `Vendor` only if target accepts it | Validate target lookup |
| `vendor_type_id` | No standard source | Blank unless target ID supplied |
| `vendor_approval_status` | `Deactivated` if `INACTIVE=1`, else project-approved active status (commonly `Approved`) | Accepted enum, commonly `Awaiting_Review`, `Approved`, or `Deactivated`; payment term is required for Approved vendors |
| `uei (Unique Entity Identifier)` | No standard source | Blank unless supplied |
| `duns (Dun & Bradstreet Number)` | No standard source | Blank unless supplied |
| `additional_languages` | No standard source | Blank unless supplied |

Select primary address for vendor-level state using priority `TYPEID 7` Primary, `5` Pay/Remit, `4` Order, `1` Billing, then `ORDER`, then `ADDRESSID`. Confirm IDs from `AFtyp`; if labels disagree, labels/current data win.

Select the primary phone by a confirmed Primary type (Swatara uses `TYPEID=9`), then `ORDER`, then `PHONEID`. Select fax by a confirmed Fax type (Swatara uses `TYPEID=8`).

## Sheet `contacts`

Create rows from active `AFcon`; use `AFlst` names/email only when it represents a real contact. Do not fabricate names from the company name.

| OpenGov column | AccuFund mapping | Validation |
|---|---|---|
| `vendor_import_key*` | `AFcon.LISTID` or `AFlst.LISTID` | Must exist on `vendors` |
| `first_name*` | `AFcon.FNAME`, fallback `AFlst.FNAME` | Required |
| `last_name*` | `AFcon.LNAME`, fallback `AFlst.LNAME` | Required |
| `job_title` | `AFcon.TITLE` | Optional |
| `phone_country_code` | `+1` when selected contact phone valid | Optional |
| `phone_number` | `AFphn` joined by `LISTID+CONTACTID`; party phone only for `AFlst` contact | Normalize/validate |
| `phone_ext` | Selected `EXTENSION` | Digits |
| `email*` | Contact email, fallback party email only for party-derived row | Required and valid |

Suppress rows lacking either required name or email. Deduplicate by `(vendor key, normalized email, normalized first name, normalized last name)`.

## Sheet `addresses`

Prefer preserving distinct valid addresses. If project rules require one address, choose Remit, Primary, Billing, Order using confirmed type labels and record the collapse.

| OpenGov column | AccuFund mapping | Validation |
|---|---|---|
| `vendor_import_key*` | `AFadr.LISTID` | Parent must exist |
| `address_line_1*` | First nonblank of `STREET1`, `STREET2` | Required |
| `address_line_2` | `STREET2` only when `STREET1` populated | Avoid duplicate line |
| `city*` | `CITY` | Required |
| `state*` | uppercase `STATE` | Required; normally 2-character US code |
| `zip_code*` | `ZIPCODE` as text | Required; preserve leading zero; validate ZIP5/ZIP+4 for US |
| `country*` | normalized `COUNTRY` | Required; approved default `United States` only for known US data |
| `default_for` | map address type to `REMIT TO`, `PRIMARY`, `ORDER FROM` | Use only accepted roles; at most one default per role |

Suggested type mapping after confirming `AFtyp`: `5→REMIT TO`, `7→PRIMARY`, `4→ORDER FROM`, `1→PRIMARY/BILLING per template capability`.

## Categories and certificate sheets

Sheets and exact headers:

- `categories`: `vendor_import_key*`, `NIGP`, `NAICS`, `UNSPSC`
- `Business Certificate`: key, `certificate_type*`, `certifying_agency`, `certificate_number`, `expiry_date*`, `issue_date*`
- `Tax Certificate`: key, `certificate_type*`, `expiry_date*`, `issue_date*`
- `Insurance Certificate`: key, `certificate_type*`, `insurer_name`, `policy_number`, `expiry_date*`, `issue_date*`
- `Other Certificates`: key, `certificate_type`, `certificate_name*`, `expiry_date*`, `issue_date*`

The standard AccuFund sources above do not prove these values. Leave sheets header-only unless dedicated source data is supplied. Validate code sets, required values, `issue_date <= expiry_date`, and parent key existence.

## Payment-method sheets

| Sheet / columns | AccuFund mapping | Validation |
|---|---|---|
| `pm_ach`: key, `is_default`, `account_type*`, `account_number*`, `routing_number*` | `AFeft`; `ACCOUNTTYPE 1→CHECKING`, `2→SAVINGS`; account=`BANKACCOUNT`; routing=`BANKDFI` | Both account/routing required; valid account type; 9-digit ABA checksum |
| `pm_check`: key, `is_default`, `payee_name*` | key=`AFlst.LISTID`; payee=`AFlst.NAME` | Emit for check-pay vendors; required payee |
| `pm_wire`: key, `is_default`, `account_number*`, `routing_number*` | Only `AFeft` rows whose `EFTTYPE` is confirmed as wire | Never guess wire codes |
| `pm_card`: key, `is_default`, `last_four` | No standard source | Header-only unless supplied |
| `pm_cash`: key, `is_default` | No standard source | Header-only unless supplied |
| `pm_transfer`: key, `is_default` | No standard source | Header-only unless supplied |

For each vendor, emit no more than one default payment method unless current OpenGov instructions explicitly permit it. If ACH is valid and approved, normally mark one ACH row default and make check nondefault or omit check according to migration policy.

## Validation and reconciliation

Fail before delivery on any blocker:

- Missing/duplicate vendor key, company name, tax type, tax ID, payment term, or external code.
- Child key absent from `vendors`.
- Duplicate external system code or normalized TIN.
- Invalid required contact/address/payment-method fields.
- Payment term, vendor type, approval status, state, country, address role, or account type not accepted by target.
- Multiple defaults for the same vendor/role.
- Unmasked sensitive data in logs or QA reports.

Reconcile:

```text
eligible AccuFund vendor keys = OpenGov vendors keys
all child keys subset of vendors keys
active + deactivated output count = vendor output count
valid ACH + check-only + other-method classifications = vendor population under approved policy
```

## Required deliverables

1. Unmodified-template `.xlsx` populated only in valid sheets/columns.
2. Mapping manifest: source table/column → target sheet/column, transform, requirement, lookup, validation.
3. Validation report with PASS/FAIL, row counts, rejected rows, duplicate keys, and masked examples.
4. Assumptions/blockers list, especially missing TINs, uncertain type codes, unsupported sheets, and target lookup values.

Do not call the workbook upload-ready until every blocker is resolved and target lookups have been validated.
