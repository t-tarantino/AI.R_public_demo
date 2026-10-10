# AI.Richie — import specification (orders & expenses)

This is the **single, authoritative** description of the JSON accepted by the
Richie importer and of every check the app performs on it. The Richie page
builds the chat prompt directly from the marked sections of this file (plus the
live master data), so what you read here is exactly what the AI is told.

> Keeping it true: whoever changes `app/services/order_import.py` or
> `app/services/expense_import.py` MUST update the matching section here.

How the file is used: `common` + the chosen kind section (`orders`, `expenses`,
`stock`, `work` or `transfers`) → prompt.

<!-- BEGIN:common -->
# 1. GENERAL RULES (apply to every file)

## 1.1 Golden rule
**Transcribe faithfully, never interpret.** Write down only what the registro
says. Do NOT compute anything (no unit prices, no totals, no discounts you
derived yourself), do NOT correct apparent mistakes, do NOT invent values, do
NOT merge or split lines. The app does all mapping and arithmetic. If a value
is not written in the registro, omit the field (or use `null`).

## 1.2 Output format
- Reply with ONE valid JSON object and nothing else: no explanations, no
  markdown fences, no comments, no trailing commas.
- Every key is lower-case, exactly as named in this specification. Do not add
  keys that are not listed (they are ignored).
- Top level always contains `"schema_version": 1` and `"kind"` (see the kind
  sections below).

## 1.3 Value formats
| Kind of value | Format | Examples | Never |
|---|---|---|---|
| Date | `"dd/mm/yyyy"`, or `"dd/mm"` (the current year is assumed), or `"yyyy-mm-dd"`. A string. | `"02/10/2026"`, `"02/10"`, `"2026-10-02"` | `"2 Oct"`, `"02.10.2026"`, weekday names |
| Money | a JSON **number**, dot as decimal separator, no currency sign, no thousands separator. Euros. | `87`, `12.5`, `321.30` | `"87€"`, `"1.234,50"`, `"€ 87"` |
| Quantity | a positive JSON integer | `2` | `"2"`, `0`, `2.5` |
| Percentage | a JSON number between 0 and 100 (no `%` sign) | `10` | `"10%"`, `0.1` |
| Text | a JSON string, as written | `"CHIC"` | |
| Absent value | omit the key, or `null` | | empty string `""` as a placeholder |
| Codes (colour, product, party, COD) | see the field description; colour, product and composition codes are **strings** copied **exactly** from the lists | `"045"`, `"16"`, `"05L"`, `"P01"` | |

## 1.4 The four row statuses
The app answers every row of a file with exactly one status:

| Status | Meaning | What happens on commit |
|---|---|---|
| `ok` | All checks passed. | The row is created. |
| `doubt` | Created data is usable but something needs a human look (price differs from list, unknown colour dropped, …). The messages explain. | The row **is created** (orders as `draft`) and the doubt reasons are **copied into its comment**, so the uncertainty is traceable and can be fixed later in the app. |
| `error` | The row cannot be created (unknown location/customer/COD, **name that disagrees with the COD**, invalid date, bad quantity, …). | The row is **skipped**. |
| `duplicate` | The same thing is already in the system (or earlier in the same file). | The row is **skipped**. |

## 1.5 Workflow, partial commit and re-sending a file
1. **Preview** (dry-run) shows the status and messages of every row; nothing is written.
2. **Create** writes every `ok` and `doubt` row and skips `error` and `duplicate` rows.
   It is deliberately **row by row, not all-or-nothing**.
3. If some rows were `error`, fix them in the file and send **the whole file
   again**: the rows already created now come back as `duplicate` and are
   skipped, so nothing is created twice and only the fixed rows are added.
   (Fixing a `doubt` row after creation is done by editing the created
   order/expense in the app, not by re-sending.)
4. Created rows carry the marker `[richie]` in their comment; it is only a
   provenance marker (the app shows "Order written by AI.Richie …") and is NOT
   used for duplicate detection.

## 1.6 Checksums
`stated_*` fields are optional numbers copied from the registro (totals as
written). They never change what is saved; they only make the app tell you
when the registro's own arithmetic and the app's arithmetic disagree. Provide
them whenever the registro shows the corresponding total.
<!-- END:common -->

<!-- BEGIN:orders -->
# 2. KIND `orders_batch`

An order = **one customer's event in one location on one date**. The app
assumes there is **never more than one order per location per day**.

## 2.1 Top level
```json
{
  "schema_version": 1,
  "kind": "orders_batch",
  "default_customer": "RVH",
  "discount_percent": 10,
  "orders": [ ],
  "stated_gross_total": 357,
  "stated_net_total": 321.30
}
```
| Field | Type | Required | Meaning |
|---|---|---|---|
| `schema_version` | integer | yes | Always `1`. |
| `kind` | string | yes | Always `"orders_batch"`. |
| `default_customer` | string | no | Customer (code or exact name) used by every order that has no own `customer`. Use it when the whole registro belongs to one customer. |
| `discount_percent` | number 0–100 | no | Default discount applied by the app to every line of every order that has no own `discount_percent`. Use it for a discount stated once for the whole registro/weekend. Omit if none. |
| `orders` | array | yes | One object per location per day (2.2). |
| `stated_gross_total` | number | no | Overall total BEFORE discount, as written. |
| `stated_net_total` | number | no | Overall total AFTER discount, as written. |

## 2.2 Order object
```json
{
  "location": "TERRAZZA",
  "date": "02/10/2026",
  "customer": "RVH",
  "discount_percent": 10,
  "stated_total": 87,
  "comment": "birthday, 30 balloons",
  "items": [ ]
}
```
| Field | Type | Required | Meaning |
|---|---|---|---|
| `location` | string | **yes** | Venue exactly as written (`CHIC`, `TERRAZZA`, `SERRA`, …). The app resolves aliases; a name that is part of a combined venue (one written `"A/B"`) also matches either half. Case-insensitive. |
| `date` | string | **yes** | Event date (format 1.3). |
| `items` | array | **yes**, ≥ 1 | The lines (2.3). |
| `customer` | string | yes unless `default_customer` is set | Customer **code** (sigla, e.g. `RVH`) or exact **name**. Must be a party flagged as customer. Never guess a customer: if it is not written and not given by the user, leave it out. |
| `discount_percent` | number 0–100 | no | Discount for THIS order only; overrides the batch `discount_percent`. |
| `stated_total` | number | no | This order's total BEFORE discount, as written. |
| `comment` | string | no | Free note for the order, as written. Do not put codes/tags here. |

## 2.3 Line object (`items[]`)
```json
{ "cod": "16", "name": "Nuvoletta con numero", "qty": 1, "line_total": 40,
  "colors": ["045", "088"], "numbers": [ {"digit": "3"}, {"digit": "0"} ], "note": "" }
```
| Field | Type | Required | Meaning |
|---|---|---|---|
| `cod` | string or null | yes (null if the registro has no COD) | Composition code **exactly as in the price list** (`"16"`, `"05L"`, `"P01"`, `"TND"`). Colonne and combos have letter codes — do NOT force them into a plain number. A bare number may also be written as a JSON integer (`16`). |
| `name` | string | recommended | Name exactly as written; used only to cross-check against the COD. |
| `qty` | integer > 0 | **yes** | Quantity of that composition. |
| `line_total` | number ≥ 0 | **yes** | The total for the WHOLE line (all `qty`), BEFORE discount, as written. Never the unit price. |
| `colors` | array of strings | no (default `[]`) | Colour codes as written, e.g. `["045","088"]`, as strings with leading zeros kept. |
| `color_surcharges` | object | no | Explicit surcharge in EUR per colour code, overriding the automatic +10% an off-catalogue colour adds. Use `{"101": 0}` when an off-catalogue colour was used but NOT surcharged on the registro. |
| `numbers` | array of objects | only for number compositions | The foil-number digits for this line (2.3.1). One object per digit (an age `30` → two objects, `"3"` and `"0"`). |
| `note` | string | no | Free text for the line. |

One object per line of the registro, in order. Same COD twice = two lines.

### 2.3.1 Number object (`numbers[]`)
Give this **only** when the composition includes a foil number (its name usually
says "numero"). Transcribe the digits written on the registro; do NOT invent them.
```json
{ "digit": "3", "color": "088", "quantity": 1 }
```
| Field | Type | Required | Meaning |
|---|---|---|---|
| `digit` | string | **yes** | A single digit `"0"`–`"9"`. One object per digit. |
| `color` | string | no | Colour **code** for this digit. Omit it to use the default (silver, or gold when the item's own colours include gold). |
| `quantity` | integer > 0 | no (default `1`) | How many of this exact digit, if the registro states more than one. |

The number's **size** is taken automatically from the composition — never write it.
A number composition sent **without** `numbers` defaults to **"18"** (digits 1 and
8, in the default colour), exactly like a hand-entered order; override it later in
the app if the real number was different.

## 2.4 What the app computes (never write these)
- composition = the price-list entry whose code equals `cod` (matched exactly,
  case-insensitive; a bare number also matches its zero-padded form, `16` → `016`);
- unit price = `line_total ÷ qty` rounded to cents;
- off-catalogue colour surcharge = `unit price × qty × 10%` per off-catalogue colour (the
  discount applies to it too), exactly like an order entered by hand — unless
  `color_surcharges` sets an explicit amount for that colour (e.g. `0` to cancel it);
- the discount that applies = the order's `discount_percent`, else the batch's, else 0;
- **the saved order total** = the sum of the built line subtotals
  (`unit price × qty − discount + surcharges`); lines without a usable COD are not
  saved and do not count in it;
- order gross (for the checksums) = sum of every written `line_total`;
  transcription net = gross × (1 − discount ÷ 100).

## 2.5 Checks and exact messages
Statuses: **E** = error, **D** = doubt, **U** = duplicate. A row takes the most
severe status among its checks (`error` > `duplicate` > `doubt` > `ok`); every
message is reported.

| # | Check | Status | Message |
|---|---|---|---|
| O1 | `location` missing | E | `Missing location.` |
| O2 | `location` not found | E | `Unknown location: '<x>'.` |
| O3 | location is retired | D | `Location '<name>' is retired (inactive).` |
| O4 | `date` missing/unparseable | E | `Missing or invalid date: '<x>'.` |
| O5 | no customer (neither `customer` nor `default_customer`) | E | `Missing customer (no 'customer' on the order and no 'default_customer').` |
| O6 | customer not found | E | `Unknown customer: '<x>'.` |
| O7 | customer matches several parties by name | E | `Ambiguous customer: '<x>' matches several parties.` |
| O8 | party exists but is not a customer | E | `'<name>' is not flagged as a customer.` |
| O9 | order `discount_percent` outside 0–100 | E | `Discount <x>% out of range (0–100).` |
| O10 | batch `discount_percent` outside 0–100 | batch note, ignored | `Batch discount <x>% out of range (0–100): ignored.` |
| O11 | order has no lines | E | `Order has no lines.` |
| O12 | line `qty` missing/≤ 0 or `line_total` missing/< 0 | E | `Line '<name or cod>': missing/invalid quantity or total.` |
| O13 | `cod` is null | D | `Item without COD ('<name>'): map it manually.` (the line is NOT saved) |
| O14 | `cod` not in the price list | E | `COD <n> ('<name>') not in the price list.` |
| O15 | composition retired | D | `COD <n> ('<comp>') is retired (inactive).` |
| O16 | written `name` shares no word-start (first 4 letters of any word) with the composition name | **E** | `Name '<x>' doesn't match COD <n> = '<comp>': fix the name or the COD.` (we cannot know which is right, so the row is **not** created) |
| O17 | unit price ≠ list price | D | `COD <n> price: written <unit>€, list <list>€.` |
| O27 | `line_total` not divisible by `qty` to the cent | D | `Line '<name or cod>': <total>€ is not divisible by <qty>; unit price rounded to <u>€.` |
| O28 | a `numbers` digit is not a single 0–9 | D | `Number digit '<x>' invalid (need one 0–9): ignored.` |
| O29 | `numbers` given on a composition that has no number balloon | D | `Number '<d>' given but COD <n> is not a number composition: ignored.` |
| O30 | unknown `color` on a number | D | `Unknown number colour '<x>': using the default.` |
| O19 | colour code unknown | D | `Unknown colour '<x>': it will be IGNORED.` |
| O20 | colour retired | D | `Colour <code> <name> is retired (inactive).` |
| O21 | colour is off-catalogue | D | `Off-catalogue colour <code> <name>: +10% surcharge applied.` |
| O22 | `stated_total` ≠ sum of line totals | D | `Order total: written <x>€, sum of lines <y>€.` |
| O23 | **duplicate in the database** — a non-cancelled order already exists for the same location and date | U | `Duplicate: order #<id> (<state>, <customer>, <total>€) already exists for <location> on <dd/mm/yyyy>.` |
| O24 | **duplicate in the file** — an earlier row has the same location and date | U | `Duplicate: another row of this file has the same location and day.` |
| O25 | batch: `stated_gross_total` and `stated_net_total` inconsistent with the batch discount (only checked when no order has its own discount) | batch note | `Stated totals inconsistent: <gross> −<d>% = <expected>, but stated net <net>.` |
| O26 | batch: computed net (or gross when no net is stated) ≠ stated total | report flag | `checksum_ok = false` |

Notes:
- A row that is both an error and a duplicate stays `error` (both messages shown).
- An earlier row of the file reserves its (location, date) even when that row
  is itself an `error`: a later row for the same day is then a duplicate.
- The duplicate rule ignores the content: same location + same date is a
  duplicate even if the lines differ. Cancelled orders do not count.
- A row whose location or date is invalid cannot be checked for duplicates.
- Lines without a resolvable COD (O13, O14) are not saved and their money is
  excluded from the saved order total; the order is created only if at least one
  line is saved. If nothing can be saved the row says so and nothing is created.
- All created orders are `draft`, linked to the resolved customer, with
  `total_price` = net total and each line carrying the applied discount.
- Foil numbers are built from `numbers` (size from the composition, colour
  defaulting to silver/gold). A number composition with no written digits defaults
  to "18" (digits 1 and 8), editable later in the app.

## 2.6 Complete example
```json
{
  "schema_version": 1,
  "kind": "orders_batch",
  "default_customer": "RVH",
  "discount_percent": 10,
  "orders": [
    {
      "location": "SERRA",
      "date": "02/10/2026",
      "stated_total": 80,
      "items": [
        { "cod": "16", "name": "Grappolo Elio", "qty": 2, "line_total": 40, "colors": ["045", "088"] },
        { "cod": "05M", "name": "Nuvoletta con numero", "qty": 1, "line_total": 40, "colors": ["045"],
          "numbers": [ { "digit": "3" }, { "digit": "0" } ] }
      ]
    },
    {
      "location": "CHIC",
      "date": "03/10/2026",
      "customer": "Mario Rossi",
      "discount_percent": 0,
      "comment": "paid in cash",
      "items": [
        { "cod": "16", "name": "Grappolo Elio", "qty": 1, "line_total": 20, "colors": ["045"] }
      ]
    }
  ],
  "stated_gross_total": 100
}
```
<!-- END:orders -->

<!-- BEGIN:expenses -->
# 3. KIND `expenses_batch`

An expense = **one payment event from one party (payer) to another (payee) on
one date**, made of one or more lines.

## 3.1 Top level
```json
{
  "schema_version": 1,
  "kind": "expenses_batch",
  "default_paid_by": "RVH",
  "expenses": [ ],
  "stated_total": 493.16
}
```
| Field | Type | Required | Meaning |
|---|---|---|---|
| `schema_version` | integer | yes | Always `1`. |
| `kind` | string | yes | Always `"expenses_batch"`. |
| `default_paid_by` | string | no | Payer (code or exact name) used by every expense without its own `paid_by`. |
| `expenses` | array | yes | One object per payment (3.2). |
| `stated_total` | number | no | Overall total of all expenses, as written. Checksum only. |

## 3.2 Expense object
```json
{
  "date": "04/09/2026",
  "paid_by": "RVH",
  "paid_to": "AMZ",
  "payment_method": "card",
  "stated_total": 120.50,
  "comment": "order #123",
  "items": [ ]
}
```
| Field | Type | Required | Meaning |
|---|---|---|---|
| `date` | string | **yes** | Payment date (format 1.3). |
| `paid_by` | string | yes unless `default_paid_by` is set | Who paid: party **code** (sigla) or exact **name** (any party). |
| `paid_to` | string | **yes** | Who received the money: party code or exact name (should be a supplier or worker). |
| `payment_method` | string | no | e.g. `card`, `cash`, `transfer`, as written. |
| `items` | array | **yes**, ≥ 1 | The lines (3.3). |
| `stated_total` | number | no | Total of this payment as written. Checksum only. |
| `comment` | string | no | Free note, as written. |

## 3.3 Line object (`items[]`)
```json
{ "product_code": "RED-AMZ-G", "description": "Red balloons 30cm", "qty": 2,
  "line_total": 24.00, "category": "materials", "variant": "3", "note": "" }
```
| Field | Type | Required | Meaning |
|---|---|---|---|
| `product_code` | string | one of `product_code` / `description` | Code of a catalogue product (see the product list). Buying a known product raises stock automatically. Leave out when the line is not a catalogue product (parking, fuel, software…). |
| `description` | string | one of the two | What was bought, as written. |
| `qty` | integer > 0 | **yes** | Quantity bought, in purchased units (packs if the product is sold in packs). |
| `line_total` | number ≥ 0 | **yes** | Total paid for the WHOLE line, as written. Never the unit cost. |
| `category` | string | yes unless `product_code` is given (then defaults to `materials`) | Expense category name exactly as in the category list. |
| `variant` | string | no | Single digit `"0"`–`"9"`, only for number-balloon products. |
| `note` | string | no | Free text for the line. |

## 3.4 What the app computes (never write these)
- unit cost = `line_total ÷ qty` rounded to cents;
- saved `total_cost` = sum of (unit cost × qty) of the lines. **The sum of
  the lines is the truth**; `stated_total` never overrides it.
- a line with a known `product_code` also creates a stock **purchase**
  movement (pieces = qty × the product's pack size), exactly like an expense
  entered by hand.

## 3.5 Checks and exact messages
Statuses: **E** = error, **D** = doubt, **U** = duplicate.

| # | Check | Status | Message |
|---|---|---|---|
| X1 | `date` missing/unparseable | E | `Missing or invalid date: '<x>'.` |
| X2 | no payer (neither `paid_by` nor `default_paid_by`) | E | `Missing payer (no 'paid_by' and no 'default_paid_by').` |
| X3 | payer unknown / ambiguous | E | `Unknown payer: '<x>'.` / `Ambiguous payer: '<x>'.` |
| X4 | `paid_to` missing | E | `Missing payee ('paid_to').` |
| X5 | payee unknown / ambiguous | E | `Unknown payee: '<x>'.` / `Ambiguous payee: '<x>'.` |
| X6 | payee exists but is neither supplier nor worker | D | `'<name>' is not flagged as a supplier or worker.` |
| X7 | payer and payee are the same party | E | `Payer and payee are the same party.` |
| X8 | no lines | E | `Expense has no lines.` |
| X9 | `qty` missing/≤ 0 or `line_total` missing/< 0 | E | `Line '<label>': missing/invalid quantity or total.` |
| X10 | line total not divisible by qty to the cent | D | `Line '<label>': <total>€ is not divisible by <qty>; unit cost rounded to <u>€.` |
| X11 | neither `product_code` nor `description` | E | `Line <n>: needs a 'product_code' or a 'description'.` |
| X12 | `product_code` unknown | D | `Unknown product code '<x>': line saved WITHOUT product (no stock refill).` |
| X13 | `product_code` matches several products | D | `Product code '<x>' is ambiguous: line saved WITHOUT product (no stock refill).` |
| X14 | product retired | D | `Product '<code>' is retired (inactive).` |
| X22 | product's unit cost ≠ its default price | D | `Product '<code>' cost: written <unit>€, usual <default>€.` |
| X15 | no `category` and no `product_code` | E | `Line '<label>': missing category.` |
| X16 | category not in the list | E | `Line '<label>': unknown category '<x>'.` |
| X17 | `variant` given but invalid (not one digit) or no known product | D | `Line '<label>': variant '<x>' ignored (needs a known product and a single digit).` |
| X18 | `stated_total` ≠ sum of lines | D | `Expense total: written <x>€, sum of lines <y>€ (the sum of lines is what gets saved).` |
| X19 | **duplicate in the database** — an expense with the same date, payer, payee and total exists | U | `Duplicate: an expense with the same date, payer, payee and total (<t>€) already exists.` |
| X20 | **duplicate in the file** — an earlier row that is not an `error` has the same date, payer, payee and total | U | `Duplicate: another row of this file has the same date, payer, payee and total.` |
| X21 | batch: sum of all totals ≠ `stated_total` | report flag | `checksum_ok = false` |

Notes:
- `<label>` = the line's `description`, else its `product_code`, else `line <n>`.
- Two genuinely different payments with the same date, payer, payee **and**
  total are indistinguishable: the second one is reported as duplicate. If that
  is real, create it by hand in the app.
- A row is created only if ALL its lines are valid (an error in any line makes
  the whole expense `error`).

## 3.6 Complete example
```json
{
  "schema_version": 1,
  "kind": "expenses_batch",
  "default_paid_by": "RVH",
  "expenses": [
    {
      "date": "04/09/2026",
      "paid_to": "AMZ",
      "payment_method": "card",
      "stated_total": 36.00,
      "items": [
        { "product_code": "RED-AMZ-G", "description": "Red balloons 30cm", "qty": 2, "line_total": 24.00 },
        { "description": "Shipping", "qty": 1, "line_total": 12.00, "category": "transport" }
      ]
    }
  ],
  "stated_total": 36.00
}
```
<!-- END:expenses -->

<!-- BEGIN:stock -->
# 4. KIND `stock_batch`

A **manual** stock change: a recount, a loss or a gift. Purchases are NOT entered
here (they come from an expense) and neither is order consumption (automatic).

## 4.1 Top level
```json
{ "schema_version": 1, "kind": "stock_batch", "updates": [ ] }
```
| Field | Type | Required | Meaning |
|---|---|---|---|
| `schema_version` | integer | yes | Always `1`. |
| `kind` | string | yes | Always `"stock_batch"`. |
| `updates` | array | yes | One object per stock document (4.2). |

## 4.2 Update object
```json
{ "type": "recount", "date": "02/10/2026", "comment": "monthly count",
  "items": [ ] }
```
| Field | Type | Required | Meaning |
|---|---|---|---|
| `type` | string | **yes** | `recount` (the counted absolute quantity), `loss` (quantity lost), or `gift` (quantity received free). |
| `date` | string | **yes** | Date of the count/loss/gift (format 1.3). |
| `items` | array | **yes**, ≥ 1 | The lines (4.3). |
| `comment` | string | no | Free note. |

## 4.3 Line object (`items[]`)
```json
{ "item": "Palloncino grande", "color_code": "045", "color_name": "Rosso",
  "variant": "3", "quantity": 20 }
```
| Field | Type | Required | Meaning |
|---|---|---|---|
| `item` | string | **yes** | Material name **exactly** as in the materials list. |
| `color_code` | string | **yes for coloured materials** | Colour **code** from the COLOURS list. |
| `color_name` | string | **yes for coloured materials** | Colour **name** matching that code (write BOTH; the app checks they agree). |
| `variant` | string | only for number materials | Digit `"0"`–`"9"`. |
| `quantity` | integer | **yes** | For `recount` the counted quantity now on the shelf (**may be `0`** = empty); for `loss`/`gift` a positive amount (> 0). The app computes the signed change (recount = counted − current). |
| `note` | string | no | Free text. |

**Colours (important):** for a coloured material you MUST provide BOTH `color_code`
and `color_name`, and they must match the COLOURS list. If they don't match, the
line is an **error** (fix it) — the app never guesses or silently drops the colour.
Non-coloured materials take no colour.

**One recount per cell:** within a file, give at most ONE `recount` line per
(material + colour + digit). Two recounts of the same cell are contradictory and
both fail.

## 4.4 Checks (E=error, D=doubt, U=duplicate)
Lines are handled **independently**: the valid lines of an update are created even
if others fail; the failed ones are reported so you can fix them and re-send the
file (already-created lines are then recognised as duplicates and not re-added).
| # | Check | Status | Message |
|---|---|---|---|
| S1 | `type` missing / not recount·loss·gift | E | `Unknown type '<x>': use recount, loss or gift.` |
| S2 | `date` missing/invalid | E | `Missing or invalid date: '<x>'.` |
| S3 | no lines | E | `Stock update has no lines.` |
| S4 | `quantity` missing / negative / 0 on loss·gift | E | `Line '<item>': quantity must be > 0.` (recount allows 0) |
| S5 | material unknown / ambiguous | E | `Unknown material '<x>'.` / `Ambiguous material '<x>': …` |
| S6 | coloured material: colour code+name missing | E | `'<item>' is coloured — a colour code and name are required.` |
| S7 | colour code not found | E | `unknown colour code '<x>'.` |
| S8 | colour name missing / not matching the code | E | `colour code '<x>' is '<name>', not '<given>' — fix the mismatch.` |
| S9 | colour given on a non-coloured material | D | `'<item>' has no colours: colour ignored.` |
| S10 | number material without a digit / bad `variant` | D | `'<item>' is a number material but no digit was given…` / `variant '<x>' ignored …` |
| S11 | two recounts of the same material+colour+digit in the file | E | `another recount in this file already sets this material/colour/digit — ambiguous.` |
| S12 | a recount line already matches current stock | note | `'<item>': recount already matches current stock (<n>).` (line skipped) |
| S13 | an identical line already exists (DB or earlier in the file) | U | `'<item>': identical line already exists — skipped as duplicate.` |
<!-- END:stock -->

<!-- BEGIN:work -->
# 5. KIND `work_batch`

Work tracks **time and activity** of a worker. It carries no pay (wages are
recorded as expenses).

## 5.1 Top level
```json
{ "schema_version": 1, "kind": "work_batch", "default_date": "02/10/2026",
  "entries": [ ] }
```
| Field | Type | Required | Meaning |
|---|---|---|---|
| `schema_version` | integer | yes | Always `1`. |
| `kind` | string | yes | Always `"work_batch"`. |
| `default_date` | string | no | Date used by entries without their own `date`. |
| `entries` | array | yes | One object per worker-session (5.2). |

## 5.2 Entry object
```json
{ "worker": "AL", "date": "02/10/2026", "start": "09:00", "end": "17:30",
  "break_minutes": 30, "tasks": "built arches at Chic and Veranda" }
```
| Field | Type | Required | Meaning |
|---|---|---|---|
| `worker` | string | **yes** | Worker **code** (sigla) or exact **name**. Must be a party flagged as a worker. |
| `date` | string | yes unless `default_date` is set | Session day (format 1.3). |
| `start` | string | no | Start time `"HH:MM"`. |
| `end` | string | no | End time `"HH:MM"`. |
| `break_minutes` | integer ≥ 0 | no | Unpaid break, in minutes. |
| `tasks` | string | no | What was done, as written. |
| `comment` | string | no | Free note. |

## 5.3 Checks (E=error, D=doubt, U=duplicate)
| # | Check | Status | Message |
|---|---|---|---|
| W1 | worker missing / unknown / ambiguous | E | `Missing worker.` / `Unknown worker: '<x>'.` / `Ambiguous worker: …` |
| W2 | party exists but is not a worker | E | `'<name>' is not flagged as a worker.` |
| W3 | date missing/invalid | E | `Missing or invalid date: '<x>'.` |
| W4 | start or end unreadable | E | `Unreadable start time: '<x>'.` |
| W5 | only one of start/end given | D | `Only one of start/end given: duration cannot be computed.` |
| W6 | end before start | E | `End time is before start time.` |
| W7 | negative break | D | `Negative break ignored.` |
| W8 | duplicate (same worker, start, end, tasks) in DB or file | U | `Duplicate: an identical work session already exists.` |

Note: linking a session to specific orders is not done on import — add the order
links later in the app if needed.
<!-- END:work -->

<!-- BEGIN:transfers -->
# 6. KIND `transfers_batch`

A money transfer = one person gave another an amount of money on a date (e.g.
settling a debt, reimbursing a fronted expense, a customer paying). It is NOT a
purchase (that is an expense) nor a sale (that is an order).

## 6.1 Top level
```json
{ "schema_version": 1, "kind": "transfers_batch", "default_from": "RVH",
  "transfers": [ ], "stated_total": 250 }
```
| Field | Type | Required | Meaning |
|---|---|---|---|
| `schema_version` | integer | yes | Always `1`. |
| `kind` | string | yes | Always `"transfers_batch"`. |
| `default_from` | string | no | Payer used by rows without their own `from_party`. |
| `transfers` | array | yes | One object per transfer (6.2). |
| `stated_total` | number | no | Sum of all transfers, checksum only. |

## 6.2 Transfer object
```json
{ "from_party": "RVH", "to_party": "AL", "date": "02/10/2026",
  "amount": 150, "payment_method": "transfer", "comment": "reimburse Amazon order" }
```
| Field | Type | Required | Meaning |
|---|---|---|---|
| `from_party` | string | yes unless `default_from` is set | Who gave the money: party code or exact name (anyone). |
| `to_party` | string | **yes** | Who received it: party code or exact name (anyone). |
| `date` | string | **yes** | Date (format 1.3). |
| `amount` | number > 0 | **yes** | Amount moved (money format, 1.3). |
| `payment_method` | string | no | `card`, `cash`, `transfer`, as written. |
| `comment` | string | no | Free note. |

## 6.3 Checks (E=error, D=doubt, U=duplicate)
| # | Check | Status | Message |
|---|---|---|---|
| T1 | payer missing / unknown / ambiguous | E | `Missing payer …` / `Unknown payer: '<x>'.` / `Ambiguous payer: …` |
| T2 | payee missing / unknown / ambiguous | E | `Missing payee ('to_party').` / `Unknown payee: '<x>'.` / `Ambiguous payee: …` |
| T3 | payer and payee are the same | E | `Payer and payee are the same party.` |
| T4 | date missing/invalid | E | `Missing or invalid date: '<x>'.` |
| T5 | amount missing / ≤ 0 | E | `Missing or invalid amount (must be > 0).` |
| T6 | duplicate (same payer, payee, date, amount) in DB or file | U | `Duplicate: an identical transfer already exists.` |
| T7 | batch: sum ≠ `stated_total` | report flag | `checksum_ok = false` |
<!-- END:transfers -->

