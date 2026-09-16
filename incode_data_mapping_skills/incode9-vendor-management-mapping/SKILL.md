---
name: incode9-vendor-management-mapping
description: Maps Incode9 AP vendor CSV extracts to OpenGov NextGen Vendor Management bulk-import sheets. Use when the user supplies Incode9 APMASTF, APCLASSF, or related vendor files and needs column-level vendors, contacts, addresses, or payment-method outputs with validation.
---

# Incode9 Vendor Management mapping

Map Incode9 vendor extracts to the current entity-generated OpenGov NextGen Vendor Management workbook. Produce a mapping report and import-ready sheets only after all blockers pass.

## Required inputs

1. Incode9 `APMASTF.csv` (required).
2. `APCLASSF.csv` when vendor class information is needed.
3. The current Vendor Management template from the target entity.
4. Target payment-term codes and payment-method sheet definitions.
5. Optional vendor crosswalk with Incode9 vendor id and target external code.

If the current entity template is unavailable, map the baseline columns below but report `NOT READY FOR IMPORT`. Template headers, required markers, custom fields, and `pm_*` schemas override this skill.

## Source handling

- Match source headers case-insensitively after trim, but preserve source values until transformation.
- Treat blank, whitespace, `NULL`, `N/A`, `-`, and `#N/A` as null.
- Preserve vendor ids, ZIP codes, tax ids, routing numbers, and account numbers as text.
- Deduplicate `APMASTF` by trimmed `apm_vend`; when `A4GLIdentity` exists, keep the highest value only after confirming duplicates are revisions rather than separate companies.
- Never expose unmasked tax or bank data in chat, logs, or validation reports.

## Stable vendor key

Set `vendor_import_key` to the approved vendor crosswalk value when supplied; otherwise use trimmed `apm_vend`. Do not cast it to a number or remove leading zeros. Reuse the exact value on every child sheet.

## `vendors` sheet mapping

| NextGen column | Incode9 source | Transform / decision |
|---|---|---|
| `vendor_import_key` | vendor crosswalk, else `APMASTF.apm_vend` | Trim; text; unique; max 100 |
| `legal_company_name` | `APMASTF.apm_name` | Trim and collapse repeated spaces; required; max 255 |
| `doing_business_as` | No deterministic 1.0 mapping | Use an identified DBA field if present; otherwise copy `apm_name` only when the entity template requires DBA |
| `phone_country_code` | Constant when `apm_phone` is populated | Use approved country code, normally `+1` for verified US numbers |
| `phone_number` | `APMASTF.apm_phone` | Left-pad legacy numeric value to 10 digits only when source metadata confirms lost leading zeros; validate allowed phone characters and max 30 |
| `phone_ext` | No deterministic mapping | Blank unless a documented source column exists |
| `email` | Entity/customer extension, if present | Trim and lowercase; do not derive from contact names |
| `company_website` | Entity/customer extension, if present | Trim |
| `business_type` | `APMASTF.apm_class` + `APCLASSF.apcl_class`/description | Use an approved class-to-NextGen enum crosswalk; no default |
| `is_1099_applicable` | `APMASTF.apm_1099` | `false` when blank or exempt code `X`; otherwise `true` only after AP owner confirms the Incode code |
| `state_of_incorporation` | No deterministic mapping | Blank unless supplied; uppercase valid state/territory abbreviation |
| `tax_type` | `APMASTF.apm_tin_type` | `E` → `EIN`; `S` → `SSN`; any other nonblank code requires approved mapping to `FTIN` or correction |
| `tax_id` | `APMASTF.apm_tin` | Preserve as text; format EIN `##-#######` or SSN `###-##-####`; never fabricate |
| `payment_term` | APMASTF term field if present in the supplied extract | Map source value/description to the active Atlas payment-term **code**; do not guess from due dates |
| `is_separate_payment` | No deterministic mapping | `false`, unless an approved customer-specific source rule exists |
| `company_description` | `APCLASSF` description or approved source narrative | Trim; max 5000; do not substitute class code alone |
| `fax_country_code` | Constant when `apm_fax` is populated | Usually `+1` only for verified US numbers |
| `fax_number` | `APMASTF.apm_fax` | Same preservation and validation as phone |
| `fax_ext` | No deterministic mapping | Blank |
| `external_system_code` | vendor crosswalk target external code, else `APMASTF.apm_vend` | Trim; text; unique; max 100 |
| `is_one_time_vendor` | No deterministic mapping | `false`; change only from an approved one-time-vendor rule |
| `vendor_type` | Constant | `Vendor` |
| `vendor_type_id` | No deterministic mapping | Blank |
| `uei (Unique Entity Identifier)` | Entity/customer extension, if present | Uppercase, strip separators, exactly 12 alphanumeric |
| `duns (Dun & Bradstreet Number)` | Entity/customer extension, if present | Digits only, 7–13 digits |
| `additional_languages` | Entity/customer extension, if present | Approved NextGen enum names, comma-separated |
| `vendor_approval_status` | `APMASTF.apm_status`, legacy-template mode only | `A` → `Approved`; `I` → `Deactivated`; `H` → `Awaiting_Review`; unknown → blocker. Omit if the template lacks this column |

Allowed `business_type` values are: `Sole Proprietorship`, `Partnership`, `Corporation`, `LLC`, `S Corporation`, `C Corporation`, `Non Profit`, `Government Entity`, `Trust or Estate`, `Foreign Individual`, `Foreign Entity`, `NONRESIDENT WITHHOLDING`.

## `contacts` sheet mapping

Create at most one row for each nonblank numbered contact slot. Do not emit empty contact rows.

| NextGen column | Incode9 source | Transform |
|---|---|---|
| `vendor_import_key` | resolved vendor key | Exact parent key |
| `first_name` | `apm_contact1`…`apm_contact4`, if present | Parse only when the source structure reliably separates names; otherwise place the full value in the template-supported name field or flag for review |
| `last_name` | same contact slot | Use approved name parsing; never infer from a single token |
| `job_title` | corresponding title/role field, if present | Trim; max 100 |
| `phone_country_code` | constant for populated contact phone | Approved country code |
| `phone_number` | `apm_contact_phone1`…`apm_contact_phone4` | Preserve/normalize as phone; max 30 |
| `phone_ext` | corresponding extension, if present | Digits/text; max 10 |
| `email` | corresponding contact email, if present | Trim, lowercase, validate; max 254 |

The contact primary key is `vendor_import_key + email`. If email is blank and the target template permits it, check for otherwise duplicate contact rows before output.

## `addresses` sheet mapping

Use the APMASTF vendor address as the authoritative vendor-level address. Do not use invoice-specific `APADDRF` rows as vendor master addresses without vendor-owner approval.

| NextGen column | Incode9 source | Transform |
|---|---|---|
| `vendor_import_key` | resolved vendor key | Exact parent key |
| `address_line_1` | `APMASTF.apm_addr1` | Trim; max 255 |
| `address_line_2` | `APMASTF.apm_addr2` | Trim; max 255 |
| `city` | `APMASTF.apm_city` | Trim; max 100 |
| `state` | `APMASTF.apm_state` | Trim; prefer uppercase 2-letter abbreviation |
| `zip_code` | `APMASTF.apm_zip` | Preserve as text; do not drop leading zeros |
| `country` | source country if present, else constant | `US` only when US is confirmed; otherwise approved country value |
| `default_for` | Constant for the sole master address | `PRIMARY,REMIT TO,ORDER FROM` |

If multiple legitimate vendor-level addresses are supplied, emit one row each and require exactly one `PRIMARY`, one `REMIT TO`, and one `ORDER FROM`.

## Payment-method mapping

Only create a `pm_<code>` sheet that exists in the current entity template. Determine the Atlas method code from `APMASTF.apm_eft` through an approved crosswalk:

- `E` indicates an EFT candidate, not automatically an Atlas `ACH` code.
- `R` and `D` require AP-owner classification.
- Unknown or blank codes do not produce payment-method rows.

For an approved ACH-like sheet:

| Template concept | Incode9 source | Transform |
|---|---|---|
| `vendor_import_key` | resolved vendor key | Exact parent key |
| `is_default` | derived | `true` when this is the vendor's only method; otherwise exactly one method must be selected |
| account holder/payee name | `APMASTF.apm_name` | Use legal company name when blank |
| routing number | `APMASTF.apm_eft_aba` | Preserve as text; strip non-digits; must be exactly 9 digits. The legacy SQL pads to 16, which is invalid for NextGen and must not be copied |
| account number | entity/customer APMASTF EFT account field, if present | Preserve as restricted text; digits and Atlas length rules |
| account type | `APMASTF.apm_eft_acct_type` | `C` Personal Checking; `D` Commercial Checking; `S` Personal Savings; `T` Commercial Savings, then map to the exact template enum |
| advice/email | `apm_eft_advise` plus source email | `1` Email; `2` Hard Copy. Email delivery requires a valid supplied email |

Never invent static payment-method headers; copy them from the template.

## Optional sheets

- `categories`: create only from an approved AP class/category-to-NIGP/NAICS/UNSPSC crosswalk.
- `local_profiles`, certificate sheets, and `custom_fields`: no deterministic Incode9 1.0 mapping exists. Map only supplied, documented fields using exact template headers.
- Do not place attachments in the workbook.

## Validation and result

Validate:

1. Exact template sheet names and headers; file size at most 4 MB.
2. One unique vendor row per key; no duplicate nonblank external code or `tax_type + tax_id`.
3. Every child key exists in `vendors`.
4. Required entity fields and required child sheets exist for every vendor.
5. Canonical enums, booleans, dates, phones, emails, tax ids, and payment-term codes.
6. Multi-address and multi-payment-method default rules.
7. Source vendor count, output vendor count, excluded count, and reason totals reconcile.

Return a manifest containing source files, row counts, crosswalks used, output sheets/rows, warnings, blockers, and `READY FOR IMPORT` or `NOT READY FOR IMPORT`. Never mark ready while the entity template, required crosswalks, or target lookups are missing.
