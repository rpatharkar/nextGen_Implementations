# Budget Legacy → OpenGov ERP: JE Import Playbook

How to extract budget data from a legacy GL, classify it, and load it through the **same `JOURNAL_ENTRY` CSV template** used for actuals — so it passes every import and posting check.

OpenGov does **not** have a separate budget document. Budgets are journal entries whose **ledger type** tells posting which balance columns to write.

There is **no** generic ledger type named `Budget`.

| What you mean | Exact OpenGov value |
|---|---|
| Original / adopted appropriation | `Budget Adoption` |
| Supplement, reduction, ordinance | `Budget Amendment` |
| Move between accounts | `Budget Transfer` |

If `Ledger Type` is blank, the importer **defaults to `Actuals`**. Those rows will corrupt the actuals ledger.

---

## 1. Mental model (read this before touching SQL)

```
Legacy (usually one-sided amounts)          OpenGov (double-entry JEs)
──────────────────────────────────          ──────────────────────────
account + FY + budget type + amt            JE header + balanced lines

Adopted / original        ───────────────►  Ledger Type = Budget Adoption
                                            → general_ledger_details.adopted_budget_*

Amendments / ordinances   ───────────────►  Ledger Type = Budget Amendment
                                            → general_ledger_details.budget_amendment_*

Transfers / reclasses     ───────────────►  Ledger Type = Budget Transfer
                                            → general_ledger_details.budget_transfer_*
```

After posting, OpenGov **computes** (it does not store) revised and available budget:

```
revised   = adopted_net + amendment_net + transfer_net
used      = actuals_net  [+ encumbrance_net]  [+ pre_encumbrance_net]
            ↑ GL Settings → Budget Check toggles
available = revised − used
```

Nets are always **debit − credit**. That drives debit/credit convention in section 6.

Budgets **do not roll into the next fiscal year**. Each FY needs its own adoption (and amendments/transfers for that year). Within a FY, activity carries period to period.

---

## 2. What to look for in the legacy database

Do not start from a “budget report.” Start from **transactional budget activity**, then decide whether you replay history or snapshot.

### 2.1 Tables / views you typically need

Hunt for these concepts (names vary by vendor):

| Concept | Typical legacy clues | Why you need it |
|---|---|---|
| Budget activity / ledger | `budget_txn`, `gl_budget`, `appropriation`, `ba_detail` | Source of amounts |
| Budget type / ledger code | `BUDGET`, `ADOPT`, `ORIG`, `AMEND`, `BA`, `XFER`, `TRF` | Maps to the 3 OpenGov ledger types |
| Document / batch / ordinance id | `document_no`, `ordinance`, `ba_number`, `batch_id` | Becomes `Group ID` + `External JE number` |
| Line number | `line_no` | `JE Line Number` (traceability only) |
| Account / org / fund / object | COA segments | `Accounting String` (or crosswalk input) |
| Fiscal year / period / effective date | `fiscal_year`, `period`, `effective_date`, `posted_date` | `JournalDate` |
| Debit / credit **or** signed amount | `debit`, `credit`, `amount`, `increase_decrease` | OpenGov line amounts |
| Status | `posted`, `approved`, `void`, `unposted` | Import **posted/approved only** |
| Version / book | `working`, `adopted`, `revised`, `version` | Optional `Budget Name` / `Version` |

Also pull, as **reference** (not always imported as JEs):

- Current **revised** / **working** budget by account + FY (reconciliation target)
- Current **available** budget if they use budget check on day 1
- Chart of accounts + which accounts are budgetable
- Offset / budgetary fund-balance / appropriation-control accounts

### 2.2 Questions to answer on the legacy side before mapping

1. Is budget stored as **transactions** (many rows per account per year) or as a **balance snapshot** (one row per account per year)?
2. Are adoption, amendment, and transfer **separate types**, or is everything “budget” with a reason code?
3. Are amounts **one-sided** (appropriation only) or already **double-entry**?
4. Is the sign convention **positive = increase**, or debit/credit columns, or “natural balance”?
5. Are transfers stored as **two rows** (from/to) under one document, or as two independent documents?
6. Which years must land in OpenGov: current FY only, or N prior years for reporting?
7. Is the go-live mid-year (need remaining available) or at FY start (need adopted only)?

If you cannot answer (1), (3), and (4), do not build the CSV yet. Wrong answers here fail validation or pass validation and still reconcile wrong.

### 2.3 Rows to **exclude**

- Unposted, draft, rejected, voided documents
- Statistical / memo budgets that are not legal appropriations
- Encumbered remaining / available remaining (those are **computed** in OpenGov, not imported)
- “Revised budget” as a 4th type — it is `adopted + amendments + transfers`
- Net-zero placeholder lines (optional; $0 lines can insert but add noise)
- Accounts that will not exist in OpenGov COA (fix COA/crosswalk first)

### 2.4 Suggested legacy extract grain

One extract row per **posted budget line**:

```
document_id | line_no | budget_type | fy | effective_date
account_segments | debit | credit | (or signed_amount + direction)
fund | org_unit | status | source_system_id
budget_name | budget_id | version
```

You will **reshape** this into balanced JE groups. Do not dump this grain 1:1 into the template unless legacy is already double-entry and fund-balanced.

---

## 3. Classify each legacy row into an OpenGov ledger type

Use **document type**, not the current remaining balance.

| Legacy meaning | OpenGov `Ledger Type` | OpenGov `TransactionType` |
|---|---|---|
| Original adopted / beginning appropriation / adopted budget book | `Budget Adoption` | `Budget Adoption` |
| Supplemental appropriation, reduction, ordinance, BA | `Budget Amendment` | `Budget Amendment` |
| Transfer in/out, reclass between budget accounts, same-document from/to | `Budget Transfer` | `Budget Transfer` |
| Unknown / cannot classify and you still need GL source | same ledger type | `Manual` (valid with GL) |

**Do not** put current revised budget into Adoption unless you have explicitly chosen the **snapshot** strategy (section 4).

Valid source + type combinations for conversion (from `je_type_master.csv`):

```
Budget Adoption   + GL + Budget Adoption
Budget Adoption   + GL + Manual
Budget Amendment  + GL + Budget Amendment
Budget Amendment  + GL + Manual
Budget Transfer   + GL + Budget Transfer
Budget Transfer   + GL + Manual
```

Leave `JE Source Value` blank. The transformer defaults to **`GL`**. Do **not** use `BnP` — that is the live Budget & Performance integration, not legacy conversion.

If you invent a combination (e.g. `Budget Adoption` + `GL` + `Invoice Accrual`), import fails with:

`No Journal Entry Type found for {ledger}, {source}, and {transaction type}`

---

## 4. Choose a load shape (this is a business decision)

Because revised budget is a **sum of three columns**, the extract strategy changes the inquiry story.

### Option A — Snapshot (fast go-live)

One Adoption JE per account per FY. Amount = **current revised budget**.

- Amendment and Transfer columns stay 0
- Reconciles to “what we have now”
- Loses ordinance / transfer history

Use when prior-year detail is not required and go-live is at FY start.

### Option B — Full history (audit / mid-year)

Replay in economic order, original dates:

1. Original adopted → `Budget Adoption`
2. Each amendment document → `Budget Amendment`
3. Each transfer document → `Budget Transfer` (both sides in one Group ID)

Use when budget check must match live remaining, or users will drill Adopted vs Amended vs Transferred.

### Option C — Hybrid (usual production answer)

- Closed prior years: snapshot as Adoption
- Current open year: full history

**Rule:** if AP/PO budget check will run in OpenGov on day 1, current-year **revised** in OpenGov must match legacy revised, and **available** must match after actuals (and encumbrances, if those flags are on).

---

## 5. JE import template

Template: `apps/gl-server/src/assets/master-data/global/datasheets/journalEntryTemplate.csv`  
Template type: `JOURNAL_ENTRY`  
File format: CSV  
Date format (Tier 1): `M/D/YYYY`, `MM/D/YYYY`, `M/DD/YYYY`, or `MM/DD/YYYY`

### 5.1 Columns that matter for budget conversion

| CSV header | Required? | What to put |
|---|---|---|
| `Ledger Type` | **Yes for budgets** (schema says optional; blank → Actuals) | Exact: `Budget Adoption` / `Budget Amendment` / `Budget Transfer` |
| `Group ID` | **Yes in practice** (schema optional; blank merges all empty rows into one JE) | One id per source document |
| `External JE number` | Optional; unique per FY if set | Legacy document number |
| `JE Line Number` | Optional | Legacy line no (traceability) |
| `TransactionType` | Optional; blank → `Manual` | Match ledger type, or `Manual` |
| `JournalDate` | **Required** | Date inside the target open fiscal period |
| `Accounting String` | **Required** | OpenGov formatted string, **or** legacy string if inbound crosswalk is selected |
| `DebitAmount` | Optional | ≥ 0, max 2 decimals; see section 6 |
| `CreditAmount` | Optional | ≥ 0, max 2 decimals; see section 6 |
| `Organization Unit` | Optional; blank → entity primary org unit | Must match the **account’s** org unit |
| `JE Description` | Optional | Header description (taken from **first row** of the group) |
| `JE Line Description` | Optional | Line description |
| `Budget ID` | Optional | Legacy budget id (not mandatory) |
| `Budget Name` | Optional | Legacy book/name |
| `Version` | Optional | Legacy version |
| `Adjustment Period` | Optional | Only if posting to adj period: `{13\|14\|15}{YYYY}` e.g. `132026` |
| `JE Source Value` | Not on the stock CSV; default `GL` | Add the column only if you must override; use `GL` |

All other attribute columns (Vendor, PO, Asset, …) can stay empty. For these three transaction types they are **not mandatory**.

### 5.2 Header consistency inside one Group ID

The transformer builds **one JE from the first row** of the group, then every subsequent row is a line. If two rows share a Group ID but have different `Ledger Type`, `JournalDate`, `TransactionType`, or `Organization Unit`, **only the first row wins**. The rest silently inherit it.

**Rule:** Group ID = one document = one ledger type = one date = one org unit = one transaction type.

### 5.3 External JE number uniqueness

If `External JE number` is populated, it must be unique within the **entity + fiscal year** (case-insensitive), both inside the file and against JEs already in OpenGov.

Leave it blank if you cannot guarantee uniqueness. Do not reuse actuals’ external numbers.

---

## 6. Debit / credit and balancing (this is where extracts fail)

### 6.1 Line amount rules (import + posting)

- Amounts cannot be **negative**. Encode decreases by putting the amount on the **opposite side**, not as `-1000`.
- A line cannot have **both** debit > 0 and credit > 0.
- Max **2 decimal places**.
- Blank amount is treated as `0`.
- $0 / $0 lines are allowed by the amount validator; still omit them.

### 6.2 Which side increases the budget?

Posted net = **debit − credit**. Budget check uses that net.

| Account object type | Normal balance | To **increase** budget | To **decrease** budget |
|---|---|---|---|
| Expenditures (and Assets) | Debit | `DebitAmount` | `CreditAmount` |
| Revenues, Liabilities, Fund Balance | Credit | `CreditAmount` | `DebitAmount` |

Expenditure adoption of $10,000:

```
Dr  100-4210-51000     10000     (expenditure — budget goes up)
Cr  100-0000-30000     10000     (budgetary offset / fund balance — same fund)
```

Revenue adoption of $50,000:

```
Dr  100-0000-30000     50000     (offset)
Cr  100-0000-41000     50000     (revenue — budget goes up)
```

Transfer $1,000 from Dept A to Dept B (same fund):

```
Cr  100-4210-51000      1000     (from — expenditure budget down)
Dr  100-4220-51000      1000     (to   — expenditure budget up)
```

If the transfer crosses funds, **each fund must still balance**. You need offset lines in **both** funds, not two one-sided lines.

### 6.3 You must invent the credit side if legacy is one-sided

Most legacy budget ledgers store “account X is appropriated $N” with no offset. OpenGov will reject that on the **normal posting** path:

- JE total debit must equal total credit
- **Each fund’s** debit must equal that fund’s credit

Pick one offset pattern and use it consistently:

1. **Per-fund budgetary offset / appropriation control account** (preferred)
2. Fund-balance account that is posting-allowed **and** budgeting-allowed (if the offset itself is on a budget ledger)

The offset account must exist in COA, be active, posting-allowed, budgeting-allowed (because the line is on a budget ledger type), allow JE source `GL`, and belong to the **same org unit** as the JE header.

### 6.4 Fund mapping for P&L accounts

For **Revenues** and **Expenditures**, OpenGov also requires:

- The account has a fund mapping
- That fund has a **net (change in fund balance) account** configured

Those net accounts are **system-managed**. Never put a Change-in-Fund-Balance (`NET_ACCOUNT`) object type on a JE line.

---

## 7. OpenGov master data that must already be true

Fix these **before** the budget file. The JE importer will not create accounts or periods.

| Check | Why it fails otherwise |
|---|---|
| Fiscal calendar exists for every FY/period you date into | `No open fiscal period found for date …` |
| Period is **open** for GL (historical consolidation is more lenient on **balance**, not on account/config) | Same period error on insert |
| COA account exists (or inbound crosswalk maps the legacy string) | `COA account segment … does not exist` |
| Account **active** | `is not active` |
| Account config **valid for JournalDate** (`validFrom` / `validTo`) | `not valid for the journal entry date` |
| Config **active** for that period | `not active for selected period` |
| `postingAllowed = true` | `Transaction posting is not allowed` |
| `budgetingAllowed = true` | `Budgeting is not allowed for account … for Budget Adoption/Amendment/Transfer` |
| Account allows JE source **GL** | `Journal entry source is not allowed` |
| Account org unit = JE org unit | `does not match journal entry org unit` |
| Object type is not Change in Fund Balance | `cannot be used in journal entry lines` |
| GL source enabled on the entity | `Journal Entry Source GL is disabled` |
| Org unit name matches if you send `Organization Unit` | unresolved org unit |

**`budgetingAllowed` is the budget-specific trap.** Actuals can post to an account that has budgeting off. Budget ledger types cannot.

---

## 8. Validation gauntlet (in order)

A row can fail at any of these layers. Prepare data so **all** of them pass.

### 8.1 Tier 1 — file / schema

- CSV headers present; `JournalDate` and `Accounting String` not empty
- Dates parse as `M/D/YYYY` … `MM/DD/YYYY` (not `YYYY-MM-DD`, not `DD/MM/YYYY`)
- Amounts parse as numbers
- No more-than-max-length strings if metadata defines maxLength

### 8.2 Transform / grouping

- Rows grouped by `Group ID`
- Header fields taken from first row of each group
- Blank `Ledger Type` → `Actuals`
- Blank `TransactionType` → `Manual`
- Blank source → `GL`

### 8.3 Insert validation (`validateSingleJournalEntry`)

- Ledger type / source / transaction type exist (exact display names)
- Source enabled
- Combination exists in JE type master
- JournalDate maps to an **open** fiscal period (or valid Adjustment Period `13|14|15` + year)
- Org unit resolves
- External JE number unique per FY (if provided)
- Each line: amounts, account exists (write access), config, **budgetingAllowed**, source allowed, org unit match, not `NET_ACCOUNT`

Fund-level DR=CR is **not** in this insert validator. It is in **posting**.

### 8.4 Posting validation (`validateJEForPosting`) — normal (non-historical) path

Everything in 8.3 plus:

- At least one line
- Fiscal period open (GL); FY not closed
- Account active
- Fund mapping + net account for Rev/Exp
- Org unit match
- Mandatory attributes (none for these three types today)
- **Fund-level debit = credit**
- **JE-level debit = credit**

If you import **without** Historical Data, auto-post (when enabled) runs this. Unbalanced JEs stay unposted or fail posting.

### 8.5 Historical path (PS onboarding — same as actuals)

1. OG employee checks **Historical Data** on import → `historicalType = HISTORICAL_DATA`
2. Insert still runs 8.3 (accounts, budgetingAllowed, JE type, period, amounts)
3. Auto-post is **skipped**
4. Run **Historical Consolidation** (per FY)
5. Consolidation groups by **period + ledger type + org unit + source + transaction type**
6. Consolidation **ignores fund/JE balance errors**
7. It still fails on account/config/budgetingAllowed/org unit/`NET_ACCOUNT`/amount sign & precision

Use `HISTORICAL_UNBALANCED_DATA` only if you cannot produce offsets. Prefer balanced files: inquiry and budget check quality depend on nets, not on “it imported.”

---

## 9. How to build the CSV (practical recipe)

1. Load OpenGov COA (or confirm it exists) with `budgetingAllowed = true` on every account that will receive budget, **including offset accounts**.
2. Load inbound crosswalk if Accounting String will be legacy format.
3. Confirm fiscal periods exist and are open for the dates you will send (or you are on the historical path and periods at least exist).
4. From legacy, keep posted budget activity only; classify type (section 3); choose snapshot vs history (section 4).
5. For each source document:
   - Assign a unique `Group ID` (e.g. `{FY}-{DOC_TYPE}-{DOC_ID}`)
   - Set `Ledger Type` and `TransactionType` on **every** row of the group (same values)
   - Set `JournalDate` to the document effective date (must fall in the intended period)
   - Map each legacy line to Debit **or** Credit using section 6
   - Add offset line(s) so **each fund** in that Group ID has DR = CR
6. Drop $0 lines, voided docs, revised-budget snapshot rows if you already replayed history.
7. Validate locally before upload:

```text
Per Group ID:
  - exactly one distinct Ledger Type, TransactionType, JournalDate, Organization Unit
  - sum(DebitAmount) = sum(CreditAmount)
  - per fund: sum(Debit) = sum(Credit)
  - no row with both Debit and Credit > 0
  - no negative amounts
  - no more than 2 decimals
  - Ledger Type in {Budget Adoption, Budget Amendment, Budget Transfer}
  - Accounting String non-empty
```

8. Import as `JOURNAL_ENTRY`. For conversion, use Historical Data (same as actuals), then run Historical Consolidation.
9. Reconcile (section 11).

### 9.1 Minimal example (two-line adoption, one fund)

Headers can be the full template; unused attributes empty.

```csv
Ledger Type,Group ID,External JE number,JE Line Number,TransactionType,JournalDate,Accounting String,DebitAmount,CreditAmount,Organization Unit,JE Description,JE Line Description,Budget Name,Budget ID,Version
Budget Adoption,FY2026-ADOPT-001,LEG-ADOPT-001,1,Budget Adoption,07/01/2025,100-4210-51000,10000,,Primary,FY26 Adopted Budget,Police salaries,FY26 Adopted,BGT-2026,1
Budget Adoption,FY2026-ADOPT-001,LEG-ADOPT-001,2,Budget Adoption,07/01/2025,100-0000-30000,,10000,Primary,FY26 Adopted Budget,Budgetary offset,FY26 Adopted,BGT-2026,1
```

Amendment increase, same account:

```csv
Ledger Type,Group ID,External JE number,TransactionType,JournalDate,Accounting String,DebitAmount,CreditAmount,Organization Unit,JE Description
Budget Amendment,FY2026-BA-088,LEG-BA-088,Budget Amendment,10/15/2025,100-4210-51000,2500,,Primary,Ord 88 supplemental
Budget Amendment,FY2026-BA-088,LEG-BA-088,Budget Amendment,10/15/2025,100-0000-30000,,2500,Primary,Ord 88 supplemental
```

---

## 10. Import operation (UI)

Same screen as actuals JE import.

- Template: Journal Entry
- Optional inbound crosswalk
- **Historical Data** checkbox (OG employee / `erp-ps-onboarding`): check this for conversion
- After file completes: Settings → Historical consolidation (per FY jobs)

Do not mix actuals and budget rows in one Group ID. Same file is fine if Group IDs (and ledger types) stay separate.

Load order if you split files: **Adoption → Amendment → Transfer** per FY. Columns are independent so math does not depend on order; operationally it is easier to reconcile a known state if consolidation stops halfway.

---

## 11. Reconciliation after consolidation

Do not stop at “import succeeded.” Compare OpenGov `general_ledger_details` to the legacy extract.

Per account + FY:

| OpenGov field | Should match |
|---|---|
| `adopted_budget_net` (YTD / last period) | Sum of adoption lines (debit − credit) |
| `budget_amendment_net` | Sum of amendment lines |
| `budget_transfer_net` | Sum of transfer lines |
| adopted + amendment + transfer | Legacy **revised** budget |
| that minus actuals [− enc / pre-enc] | Legacy **available** (given the same Budget Check flags) |

Reconcile **by fund and by object type**, not a single grand total. Offset accounts will have equal-and-opposite nets; excluding them from the “budgetable expenditure/revenue” total is usually what finance will compare.

Budgets must be **zero in the next FY’s opening** unless you loaded that FY too.

---

## 12. Error catalog (symptom → cause → fix)

| Message / symptom | Cause | Fix |
|---|---|---|
| Balances land in Actuals | Blank `Ledger Type` | Set exact `Budget Adoption/Amendment/Transfer` on every row |
| `No Journal Entry Type found for …` | Invalid trio of ledger/source/txn type | Use GL + matching type or Manual (section 3) |
| `Budgeting is not allowed for account …` | `budgetingAllowed` false | Fix COA config, then reimport |
| `does not exist in the chart of accounts` / `no write access` | Bad string, missing account, or no RW | COA + crosswalk + security |
| `not valid for the journal entry date` | Config `validFrom`/`validTo` misses JournalDate | Date or account config |
| `Journal entry source is not allowed` | Account does not allow GL | Add GL to account allowed sources |
| `does not match journal entry org unit` | Account org ≠ JE org | Split JEs by org unit; don’t mix |
| `cannot be used in journal entry lines` / `Change in Fund Balance` | Used net account | Use a real offset, not the system net account |
| `Credit/Debit amount cannot be negative` | Signed legacy amount | Move sign to the other column |
| `cannot have both credit and debit amounts greater than 0` | Both columns filled | One side per line |
| `cannot have more than 2 decimal places` | 3+ decimals | Round banker/half-up to 2 **before** CSV |
| `No open fiscal period found for date` | Date outside calendar or period closed | Fix date or open period / historical process |
| `Adjustment Period '…' is invalid` | Not `13\|14\|15` + 4-digit year | e.g. `132026` |
| `External Journal Entry number '…' already exists` | Duplicate in file or FY | Unique per FY or leave blank |
| `Fund level validation failed` | One-sided appropriation, or cross-fund transfer without offsets | Add per-fund offset lines |
| `Journal Entry balance validation failed` | Group not balanced | DR=CR for the Group ID |
| `Field 'JournalDate' is required` / invalid date format | ISO or EU dates | `MM/DD/YYYY` |
| One giant JE with mixed types | Blank `Group ID` | Unique Group ID per document |
| Amendment numbers in Adoption column | Snapshot strategy, or misclassified type | Reclassify or accept snapshot (section 4) |
| Next FY still shows last year’s budget | You expected roll-forward | Budgets do not roll; load that FY |

---

## 13. Pre-flight checklist (print this)

**Legacy**

- [ ] Posted/approved budget activity only
- [ ] Every row classified Adoption / Amendment / Transfer
- [ ] Snapshot vs history vs hybrid decided and documented
- [ ] Signed amounts converted to non-negative debit **or** credit
- [ ] Transfers kept as one document (from + to)
- [ ] Revised/available control totals saved for recon

**OpenGov**

- [ ] COA loaded; budgetingAllowed on budget **and** offset accounts
- [ ] GL allowed on those accounts
- [ ] Offset accounts exist per fund
- [ ] Fund → net account mapping exists (Rev/Exp)
- [ ] Org units match
- [ ] Fiscal periods exist for every JournalDate
- [ ] Inbound crosswalk tested on a sample string (if used)

**File**

- [ ] `Ledger Type` never blank
- [ ] Group ID unique per document; header fields identical inside group
- [ ] Per group and per fund: DR = CR
- [ ] Dates `MM/DD/YYYY`
- [ ] ≤ 2 decimals, no negatives, no dual-sided lines
- [ ] External JE numbers unique per FY or blank
- [ ] Historical Data checked for conversion (same as actuals)
- [ ] After load: recon by fund / object / FY against section 11

---

## 14. What this file is not

- It is not a transform script. The mapping from *your* legacy schema is the work.
- It does not load encumbrances or actuals. Those are separate JEs (`Encumbrance` / `Actuals`) on the same template.
- It does not create COA, periods, or offset accounts.

Related code (source of truth if this doc and the product drift):

- Template: `apps/gl-server/src/assets/master-data/global/datasheets/journalEntryTemplate.csv`
- JE types: `apps/gl-server/src/assets/master-data/global/je_type_master.csv`
- Defaults: `packages/backend/service-layer/src/lib/services/journal-entry/journal-entry-transform.util.ts`
- Insert validation: `journal-entry-control.service.ts` → `validateSingleJournalEntry`
- Posting validation: `journal-entry-validation.service.ts`
- Ledger columns: `packages/backend/shared-modules/src/lib/utils/ledger-field-mapping.ts`
- Available budget: `calculateBudgetFields` in `packages/backend/shared-modules/src/lib/utils/bigJsHelper.ts`
