# Vendor Data Import Guide

How to map source vendor data into the Vendor Management bulk-import workbook, including recommended steps, field-level validations, and transforms.

This guide matches the importer implemented in Vendor Management. Entity settings, approval templates, and Atlas payment-method schemas can add required fields beyond the baselines below. Always start from the **entity-generated template**.

Related agent skill: `.claude/skills/tool-vendor-import-data-mapping/`.

---

## 1. What you are producing

A workbook (`.xlsx`, `.csv`, or `.txt`, **max 4 MB**) with a required `vendors` sheet and optional child sheets. Every child row is tied to a vendor by **`vendor_import_key`**.

| Sheet | Required in file? | Role |
| ----- | ----------------- | ---- |
| `vendors` | Always | One row per vendor |
| `contacts` | Template usually includes it | People |
| `addresses` | Template usually includes it | Locations + usage tags |
| `local_profiles` | Optional | Diversity / local certifications |
| `categories` | Optional | NIGP / NAICS / UNSPSC codes |
| `Business Certificate` | Optional | Business formation / license docs |
| `Tax Certificate` | Optional | W-9 / W-8 types |
| `Insurance Certificate` | Optional | Insurance policies |
| `Other Certificates` | Optional | Free-form documents |
| `custom_fields` | Only if the entity has custom fields | One row per vendor, one column per field title |
| `pm_<code>` | One sheet per Atlas payment method | e.g. `pm_ach` |

Preview in the UI shows up to **50 rows per sheet**. Trailing `*` on a header means required; the parser strips `*`.

---

## 2. Recommended mapping steps

Work in this order. Skipping uniqueness or child-key reuse is the most common cause of failed imports.

### Step 1 — Download the entity template

Use the template for the **target entity**. It encodes:

- Which vendor fields are required
- Which child sheets are required **per vendor**
- Atlas payment-method columns
- Custom field titles

Do not map against a different entity’s file.

### Step 2 — Profile the source

For each source table/export, record:

- Grain (one vendor per row vs. repeating vendor id)
- Identifier you will use as `vendor_import_key`
- Date, phone, tax-id, and boolean formats
- Null tokens (`N/A`, `NULL`, `-`, empty)
- Whether payment terms are Atlas **codes** or English descriptions

Treat whitespace-only cells as blank.

### Step 3 — Assign `vendor_import_key`

| Rule | Detail |
| ---- | ------ |
| Unique | One key per vendor on the `vendors` sheet |
| Stable | Prefer the legacy vendor/supplier number |
| Reused | **Same value** on every contact, address, certificate, PM, and custom-field row |
| Match | Case-insensitive after trim; max length 100 |
| External id | If `external_system_code` is blank, the importer copies this key **unless** the key looks like auto-generated `VND-####` |

Never invent a new key per child row.

### Step 4 — Map the `vendors` sheet

Map identity first (`legal_company_name`, `tax_type` + `tax_id`), then remaining scalars. See [section 4](#4-vendors-sheet--field-validations-and-transforms).

### Step 5 — Explode child records

One source vendor may become many child rows. Repeat `vendor_import_key`. See [section 6](#6-child-sheets).

### Step 6 — Apply transforms before upload

Normalize enums, dates, tax IDs, emails, phones, UEI, and DUNS using [section 3](#3-shared-type-rules). The importer validates again; dirty source still fails.

### Step 7 — Apply only documented defaults

| Blank field | Applied value |
| ----------- | ------------- |
| `is_one_time_vendor` | `false` |
| `is_1099_applicable` | `false` |
| `is_separate_payment` | `false` |
| `vendor_type` | `Vendor` |
| `country` (addresses) | `US` |
| `payment_term` when status is not Approved | `NA` (Atlas NA term / all-zero ref id) |
| `external_system_code` | `vendor_import_key` (not for `VND-####`) |
| `account_holder_name` / `payee_name` | Vendor `legal_company_name` |
| Single payment method row | `is_default` = true |
| Legacy `vendor_approval_status` | `Awaiting_Review` (one-time vendors forced `Approved`) |
| Template-driven status | `Approved` if a template is used, else `Awaiting_Review` |

Do not invent other defaults.

### Step 8 — Cross-check business rules

- No duplicate `vendor_import_key`
- No duplicate `tax_type` + `tax_id` in the file
- No duplicate non-blank `external_system_code`
- No child row whose key is missing from `vendors`
- If a vendor has **two or more** addresses: exactly one `PRIMARY`, one `REMIT TO`, one `ORDER FROM`
- If a vendor has **two or more** payment methods: exactly one `is_default=true`
- Approved (or one-time, which is auto-approved in legacy mode) vendors need a real Atlas payment term when terms are required — not blank/`NA`
- Category codes must exist in Atlas for that code system

### Step 9 — Upload, read the error report, fix, re-import

Errors exclude the vendor from the preferred preview sample. Warnings (for example payee name ≠ legal name) do not.

---

## 3. Shared type rules

| Type | Transform | Valid when non-empty | Typical error |
| ---- | --------- | -------------------- | ------------- |
| string | Trim | Within min/max length; Atlas pattern if set | `VALUE_TOO_LONG` / `INVALID_PATTERN` |
| number | Coerce with `Number()` | Numeric | `INVALID_NUMBER_VALUE` |
| boolean | Lowercase | `true`,`yes`,`1`,`y` or `false`,`no`,`0`,`n` | `INVALID_BOOLEAN_VALUE` |
| email | Trim, **lowercase** | One `@`, domain contains `.`, length ≤ 254 | `INVALID_EMAIL_FORMAT` |
| phone | Trim | Only digits, spaces, `-().+`; length ≤ 30. Stored digits after stripping `[\s\-(),]` | `INVALID_PHONE_FORMAT` |
| date | Zero-pad month/day | `YYYY-MM-DD`, `YYYY/MM/DD`, `MM-DD-YYYY`, `MM/DD/YYYY` only | `INVALID_DATE_FORMAT` |
| enum | Case-insensitive match → **canonical casing** | In the allowed list (or alias map) | `INVALID_ENUM_VALUE` |
| enum_list | Split on comma, trim each | Every token in the list | `INVALID_ENUM_VALUE` |
| tax_id | Trim; keep hyphens | EIN `##-#######` or SSN `###-##-####` (hyphens optional). **FTIN**: any non-empty string when `tax_type` is `FTIN` | `INVALID_TAX_ID_FORMAT` |
| state | Uppercase | US state/territory abbreviation (includes DC, PR, VI, GU, AS, MP) | `INVALID_STATE_ABBREVIATION` |
| uei | Uppercase, strip separators | Exactly 12 letters/digits | `INVALID_UEI_FORMAT` |
| duns | Digits only | 7–13 digits | `INVALID_DUNS_FORMAT` |
| zip_code (typed) | Strip non-digits | 5 or 9 digits | `INVALID_ZIP_CODE` |
| routing_number | Strip non-digits | Exactly 9 digits | `INVALID_ROUTING_NUMBER` |
| account_number | Digits only | Length bounds (max 34 unless Atlas says otherwise) | `INVALID_ACCOUNT_NUMBER` |
| category_code | Split comma, trim | Positive integers that exist in Atlas for that system | `INVALID_CATEGORY_CODE` / `CATEGORY_CODE_NOT_IN_ATLAS` |

**Excel dates:** format cells as one of the four text patterns above. Unpadded `M/D/YYYY` and raw serial numbers fail.

**Required empty:** after defaults, a required blank cell is `REQUIRED_FIELD_EMPTY`. Optional blank is omitted (not stored as `""`).

---

## 4. Vendors sheet — field validations and transforms

`*` = may be required or optional depending on entity field requirements. `legal_company_name` is always required.

| Column | Type | Baseline required | Recommended transform | Validation / blank |
| ------ | ---- | ----------------- | --------------------- | ------------------ |
| `vendor_import_key` | string(100) | Yes | Trim; reuse on all child rows | Unique in file |
| `legal_company_name` | string(255) | Yes | Trim; collapse extra spaces | Non-empty; also fills blank PM payee names |
| `doing_business_as` | string(255) | Yes* | Trim; if source has no DBA and the field is required, copy legal name | Empty fails when required |
| `phone_country_code` | string(10) | No | Digits / `+` | Optional |
| `phone_number` | phone | No* | Keep allowed phone characters; importer strips formatting for storage | Optional unless entity requires phone |
| `phone_ext` | string(10) | No | Digits | Optional |
| `email` | email | No* | Lowercase | Format + max 254 |
| `company_website` | string | No* | Trim; do not require `https://` | Optional |
| `business_type` | enum | No* | Map source labels to canonical list below | Unknown value rejected |
| `is_1099_applicable` | boolean | No | Boolean literals; blank → **false** | |
| `state_of_incorporation` | state | Yes* | Map full state names → 2-letter abbr, uppercase | Must be a valid US/territory abbr |
| `tax_type` | enum | Yes* | `EIN`, `SSN`, or `FTIN` | |
| `tax_id` | tax_id | Yes* | Insert standard hyphenation for EIN/SSN | Unique with `tax_type` in file; existing DB pair is also rejected |
| `payment_term` | string(50) | No* | Map descriptions to Atlas **code** (canonical case). Use `NA` when no term applies and the vendor is not Approved | Invalid code rejected; Approved + blank/`NA` when terms required → error |
| `is_separate_payment` | boolean | No | Blank → **false** | |
| `company_description` | string(5000) | No* | Trim; truncate at 5000 | |
| `fax_country_code` | string(10) | No | Same as phone country | |
| `fax_number` | phone | No* | Same as `phone_number` | |
| `fax_ext` | string(10) | No | Digits | |
| `external_system_code` | string(100) | No* | Prefer true legacy id | Unique when present; blank copies key (not `VND-####`) |
| `is_one_time_vendor` | boolean | No | Blank → **false** | `TRUE` allows Employee/Customer `vendor_type` |
| `vendor_type` | enum | No | Blank → **Vendor**. Standard vendors: only blank or `Vendor` | Employee/Customer only for one-time |
| `vendor_type_id` | string(255) | No | Trim | Meaningful for one-time vendors |
| `uei (Unique Entity Identifier)` | uei | No* | Uppercase 12 alphanumeric | Header includes the parenthetical name |
| `duns (Dun & Bradstreet Number)` | duns | No* | 7–13 digits | |
| `additional_languages` | enum_list | No* | Comma-separated canonical names | |
| `vendor_approval_status` | enum | No | **Legacy imports only** | See below |

There is **no** `local_profiles` column on `vendors`. Use the `local_profiles` sheet. There is no vendors-sheet column for parent company.

### 4.1 Allowed enumerations

**business_type:** Sole Proprietorship, Partnership, Corporation, LLC, S Corporation, C Corporation, Non Profit, Government Entity, Trust or Estate, Foreign Individual, Foreign Entity, NONRESIDENT WITHHOLDING

**tax_type:** EIN, SSN, FTIN

**vendor_type:** Vendor, Employee, Customer

**additional_languages:** Spanish, Chinese (Cantonese), Chinese (Mandarin), Tagalog (Filipino), Vietnamese, French, Arabic, Korean, Others

### 4.2 Approval status (legacy mode only)

Present only when legacy import mode is on. Template-driven imports do not use this column; status is `Approved` when a template id is supplied, otherwise `Awaiting_Review`.

| Input | Stored status |
| ----- | ------------- |
| (blank) | `Awaiting_Review` |
| `Active` | `Approved` |
| `Inactive` | `Deactivated` |
| `Awaiting_Review`, `Approved`, `Deactivated` | Unchanged |
| One-time vendor | Forced `Approved` |

### 4.3 Common source header aliases

| Source header (examples) | Map to |
| ------------------------ | ------ |
| vendor id / supplier id / vendor code | `vendor_import_key` |
| company name / legal name / vendor name | `legal_company_name` |
| DBA / trade name | `doing_business_as` |
| EIN / FEIN / federal tax id / SSN | `tax_id` (set `tax_type` accordingly) |
| payment terms / terms | `payment_term` |
| website / url | `company_website` |
| phone | `phone_number` |
| zip / postal code | `addresses.zip_code` |
| street / address / address1 | `addresses.address_line_1` |

If a single `Name` column exists, map it to `legal_company_name` and copy it to `doing_business_as` when DBA is required.

---

## 5. Entity-configurable requirements

Settings can mark these vendor fields required: doing business as, business type, state of incorporation, phone, email, fax, website, description, external system code, tax info (type **and** id), UEI, DUNS, payment terms, additional languages.

These groups can be required **per vendor** (each vendor must have at least one child row): contacts, addresses, categories, each certificate category, local profiles, payment methods (any `pm_*` sheet).

Contact and address **subfields** (first name, city, zip, and so on) can also be required independently of the sheet.

Always treat the generated template headers as authoritative for a given entity.

---

## 6. Child sheets

Every child row needs `vendor_import_key` matching `vendors`. Missing key → `MISSING_PARENT_REFERENCE`. Unknown key → `ORPHAN_CHILD_RECORD`.

### 6.1 Contacts (`contacts`)

Primary key: `vendor_import_key` + `email`.

| Column | Type | Baseline required | Notes |
| ------ | ---- | ----------------- | ----- |
| `vendor_import_key` | string | Yes | FK |
| `first_name` | string(255) | No* | |
| `last_name` | string(255) | No* | |
| `job_title` | string(100) | No* | |
| `phone_country_code` / `phone_number` / `phone_ext` | string / phone / string | No* | Same phone rules as vendors |
| `email` | email | No* | Lowercase; used in the composite key |

Multiple contacts per vendor are allowed.

### 6.2 Addresses (`addresses`)

Primary key: `vendor_import_key` + `address_line_1`.

| Column | Type | Baseline required | Notes |
| ------ | ---- | ----------------- | ----- |
| `vendor_import_key` | string | Yes | FK |
| `address_line_1` | string(255) | Yes* | |
| `address_line_2` | string(255) | No* | |
| `city` | string(100) | Yes* | |
| `state` | string(50) | Yes* | Free text at baseline (not forced to 2-letter type) |
| `zip_code` | string(20) | Yes* | Free text at baseline |
| `country` | string(100) | Yes* | Blank → `US` |
| `default_for` | usage list | No* | Comma-separated: `PRIMARY`, `REMIT TO`, `ORDER FROM` (case-insensitive; stored uppercase) |

If a vendor has **one** address, usage tags are not enforced. If they have **two or more**, each of PRIMARY, REMIT TO, and ORDER FROM must appear on exactly one address.

### 6.3 Local profiles (`local_profiles`)

Primary key: `vendor_import_key` + `local_profile_type`. One row per certification type.

| Column | Type | Required | Notes |
| ------ | ---- | -------- | ----- |
| `vendor_import_key` | string | Yes | FK |
| `local_profile_type` | enum | Yes | Canonical names below |
| `certifying_agency` | string(255) | No | |
| `certificate_number` | string(100) | No | |
| `issue_date` / `expiry_date` | date | No | Strict date formats |
| `ethnicity` | enum | Conditional | Required only for MBE, CBE, and MWBE when the entity requires ethnicity |

**local_profile_type:** Airport Concessions Disadvantage Business Enterprise; Certified Small Business; Combination Business Enterprise; Disabled Veteran Business Enterprise; LGBTQ+ Owned; Micro Business; Minority Business Enterprise; Minority Women Business Enterprise; Native American Owned; Section 3; Socially and Economically Disadvantaged Business Enterprise; US DOD Service-Disabled Veteran Owned Business; US DOT Certified DBE; Veteran Owned; Woman Business Enterprise

**ethnicity:** African American; Asian; Hispanic; Native American or Alaska Native; White; Other; Prefer not to answer

### 6.4 Categories (`categories`)

Typically one row per vendor. Cells may contain **comma-separated** codes.

| Column | Type | Required | Notes |
| ------ | ---- | -------- | ----- |
| `vendor_import_key` | string | Yes | FK |
| `NIGP` | category_code | No | Positive integers; must exist in Atlas NIGP |
| `NAICS` | category_code | No | Same for NAICS |
| `UNSPSC` | category_code | No | Same for UNSPSC |

Blank code cells are skipped. Each valid code becomes its own stored category row.

### 6.5 Certificates

Four tabs. Sheet name **is** the category. `issue_date` and `expiry_date` are required on every row.

| Sheet | Type column | Other columns |
| ----- | ----------- | ------------- |
| `Business Certificate` | Required enum (articles of incorporation/organization, IRS 501(c), partnership agreement, passport copy, trust certificate, and related types) | `certifying_agency`, `certificate_number` optional |
| `Tax Certificate` | Required: `W-8BEN`, `W-8BEN-E`, `W-9` | Dates only besides type and key |
| `Insurance Certificate` | Required enum (GL, auto, workers’ comp, professional, umbrella, cyber, builder’s risk, etc.) | `insurer_name`, `policy_number` optional |
| `Other Certificates` | `certificate_type` free text; `certificate_name` used in the primary key | Dates required |

Do not put file attachments in the mapping spreadsheet (`attachment_*` columns are not mapped into the vendor entity).

### 6.6 Payment methods (`pm_*`)

Sheet name is `pm_` + lowercase Atlas payment-method code (example: ACH → `pm_ach`).

Every PM sheet includes `vendor_import_key` and `is_default`, plus dynamic columns from Atlas (`account_holder_name`, routing number, account number, and so on).

| Rule | Behavior |
| ---- | -------- |
| Payee / account holder name | Always optional in import. Blank → legal company name. Illegal characters are stripped, not rejected. A value that differs from legal name is a **warning**. |
| One PM row for the vendor | Auto-defaulted |
| Two or more PM rows | Exactly one `is_default=true` across all `pm_*` sheets |
| Routing number | 9 digits |
| Account number | Digits; length from Atlas |

Do not invent static PM columns; copy the template for that entity.

### 6.7 Custom fields (`custom_fields`)

Wide layout: **one row per vendor**. Column header = custom field **title**.

| Field type | Store as |
| ---------- | -------- |
| text / date / single dropdown | Trimmed string |
| number | Number |
| boolean | Boolean |
| multi dropdown | Array from comma-separated values |

Blank optional fields are omitted from stored JSON. Required custom fields left blank → `REQUIRED_CUSTOM_FIELD_MISSING`.

---

## 7. Mapping worksheet (use this table)

Copy into your mapping workbook:

| Source field | Source sample | Import sheet | Import column | Required? | Transform | Validation | Blank behavior | Risk / notes |
| ------------ | ------------- | ------------ | ------------- | --------- | --------- | ---------- | -------------- | ------------ |
| | | vendors | vendor_import_key | Yes | trim | unique, max 100 | error | Reuse on children |
| | | vendors | legal_company_name | Yes | trim | max 255 | error | |
| | | | | | | | | |

Flag as **blockers** before upload: unmapped required columns, invalid enums, duplicate keys or tax ids, orphan child keys, Approved vendor without a valid payment term, multi-address missing usage tags, multi-PM missing default, category codes not in Atlas.

---

## 8. System fields you do not map

The importer sets:

| Field | Value |
| ----- | ----- |
| `vendorCreationSource` | `Add_Vendor_UI_Bulk` |
| `vendorCreationSourceId` | `vendor_import_key` |
| `entityId`, `createdBy`, `updatedBy` | Import session |
| `status` | From legacy column or template rules |

---

## 9. Checklist before upload

- [ ] File is `.xlsx` / `.csv` / `.txt` and ≤ 4 MB
- [ ] `vendors` sheet present with required headers
- [ ] Every vendor has a unique `vendor_import_key`
- [ ] Child rows reuse that key exactly
- [ ] Tax type/id pairs unique in the file
- [ ] Enums and dates match allowed values/formats
- [ ] Payment terms are Atlas codes (or `NA` where allowed)
- [ ] Multi-address and multi-PM rules satisfied
- [ ] Entity-required child sheets have at least one row per vendor
- [ ] Custom field columns use **titles** from the template
