# Spec 007: Web frontend, first release (F1)

Status: Implemented (2026-11-02). Approved on 2026-11-02 by the product owner's explicit
decision, for the RC1 scope only: the four read-only modules (Dashboard, Sales analysis,
Products, Data) over the four existing endpoints, local use on `127.0.0.1` only, seed 42
synthetic data; implemented and visually accepted the same day (records in sections 13
and 15). The approval does not cover future screens or features, any API change, or any
commercial production capability (authentication, multi-company, public or cloud
deployment). History: proposed as Draft on 2026-11-01 and revised three times; decisions
D1 to D14 approved on 2026-11-01; npm packages installed and F1 implemented under
separate authorizations on 2026-11-01. Not authorized: downloading Playwright browsers.
Owner: DealPilot AI team
Depends on: spec 002 (HTTP API v1, the only data source; its contract does not change),
spec 001 (sections 4, 5.7 and 8.1, for product activity, closed days and daily averages),
`AGENTS.md` (stack: React + Vite on Node 24, built only after the API exists; English-only
product output), the design references in `DealDesign/`.

## 1. Goal
A local web interface over the spec 002 API, faithful to the official design references,
that lets a user explore the synthetic sales data: totals, trends, products and regions.
It shows only values the API returns or simple, documented transformations of them.

## 2. Approval summary

| Group | Content | Where |
|---|---|---|
| **Ready for approval** | Scope of F1, screen mapping, API mapping, functional requirements, language table, responsive rules, security rules, architecture, acceptance criteria | Sections 3 to 14 |
| **Approved 2026-11-01** | First-release direction; architecture direction; D3 = C, D4 = B, D5 = A; D1, D2, D6 to D14 with conditions | Sections 3, 6, 12, 15 |
| **Decisions needing the user's input** | None left; the spec as a whole still needs approval | Section 15 |
| **Dependencies needing separate authorization** | 19 npm packages (final proposal) and, separately, Playwright browser binaries | Section 12.9 |
| **Reserved for future releases** | Sign-in, forecasts, promotions, reports, customers, regions, settings, write actions | Section 3.2 |

Requirements that depend on a pending decision say so (for example "per D4").

## 3. Scope

### 3.1 In scope for F1
Four read-only screens over `GET /health`, `GET /v1/metadata`, `GET /v1/dimensions` and
`GET /v1/sales/metrics`, unchanged:
- **Dashboard** (`dashboard.png`),
- **Sales analysis** (`seal.png`),
- **Products** (`product_custom.png`),
- **Data** (`data_manage.png`; the sidebar label is "Data", the page is data management),

plus the application shell, a "Page not found" view and a "Data unavailable" view.

### 3.2 Reserved for future releases (each needs its own approved spec or amendment)
| Feature | Design | Why not in F1 |
|---|---|---|
| Sign-in, accounts, password reset, sign-up | `login.png` | Spec 002 has no authentication; the app is local-only (D1) |
| Forecasts page | `farecasting.png` | `/v1/forecasts` is not served (spec 002 D10, spec 003 D11); Prophet is not an approved model; spec 003 has no intervals |
| Promotions page | `promotion.png` | No promotion endpoint (spec 002 D11); "Expected lift" is a hidden generator parameter (spec 002 section 3.8) |
| Reports and exports | `reports.png` | No report contract; PDF and Excel need new dependencies |
| Customer analytics, Regions page, Settings page | sidebar only | No design and no contract |
| Write actions (generate data, new product, promotion, report, forecast) | several | The API is read-only (spec 002 section 2) |
| Expected demand on charts | `dashboard.png` | Forbidden by spec 002 section 3.8 |
| Notifications, global search, user menu | top bar | No contract |
| AI summaries | none | Spec 005 is Draft; no AI call from the frontend |

### 3.3 Screenshot mapping
| Image | Product screen? | Screen | F1 |
|---|---|---|---|
| `dashboard.png` | Yes | Dashboard | Yes, reduced |
| `seal.png` | Yes (file name kept) | Sales analysis | Yes, 3 of 5 tabs |
| `product_custom.png` | Yes | Products | Yes, read-only |
| `data_manage.png` | Yes | Data | Yes, read-only |
| `login.png` | Yes | Sign in | No |
| `farecasting.png` | Yes (file name kept) | Forecasts | No |
| `promotion.png` | Yes | Promotions | No |
| `reports.png` | Yes | Reports | No |
| `Work_screen.png` | **No**: the developer's IDE | none | Excluded |

The images are reference designs. Their numbers, names and categories (for example the
regions "Luanda" and "Benguela", the category "Boissons", "152 840" orders) are sample
content and are never shown: every value comes from the API.

## 4. API facts the frontend relies on (spec 002, unchanged)
- **`GET /health`**: `{"status": "ok", "version": "<package version>"}`; never reads data.
- **`GET /v1/metadata`**: `seed`, `start`, `end`, `generator_version`, `library_versions`
  (object or `null`), `row_counts` (object of table name to integer, may include
  `expected_demand`). Never `parameters`.
- **`GET /v1/dimensions`**: `date_range {start, end}`, `group_by`, `intervals`, `metrics`,
  `regions [{region_id, name}]` sorted by ID, `categories [string]` sorted,
  `products [{product_id, name, category, launch_date, discontinue_date|null}]` sorted by
  ID. Every product is listed, with or without sales.
- **`GET /v1/sales/metrics`**: parameters `start`, `end` (default: dataset range; never
  outside it), `group_by` (repeatable: `date`, `product`, `category`, `region`),
  `interval` (`day`, `week`, `month`; only with `group_by=date`), filters `product_id`,
  `category`, `region_id` (repeatable; OR within one, AND across). Response: `start`,
  `end`, `group_by`, `interval`, `filters`, `metrics`, `rows`, `totals`, `row_count`.
  Metrics: `units` (integer), `revenue` (USD after discounts, decimal string
  `^[0-9]+\.[0-9]{2}$`), `orders` (integer), `order_lines` (integer).
- **Only groups with sales are returned** (spec 002 D5): a missing day, month, product or
  region means zero, including closed days (Dec 25, Jan 1).
- **`orders` does not add up across product or category groups** (an order can hold
  several products); it does add up across dates and regions.
- **At most 20,000 groups** per response (`result_too_large`, spec 002 D6).
- Errors on `/v1`: body `{"error": {"code", "message", "details"}}`; codes used here:
  `invalid_date`, `invalid_date_range`, `date_out_of_range`, `invalid_filter`,
  `invalid_parameter`, `unknown_parameter`, `unsupported_dimension`, `result_too_large`,
  `not_found` (all 4xx) and `data_unavailable` (503).
- No CORS headers: pages must be served from the same origin as the API (section 12.7).

## 5. Screens: API-to-interface mapping

Common to every screen:
- **Loading**: skeletons in the shape of the final cards, tables and charts; the page
  header and tabs are shown at once.
- **Empty**: when `totals.units` is 0 for the range (no counted sales), cards show 0 and
  charts show "No sales in this period" instead of an empty plot.
- **Error**: an error panel in the affected card, with an English message chosen by
  `error.code` (section 7, FR-06) and a "Try again" button; other cards keep working. A
  503 `data_unavailable` from any call replaces the page with the "Data unavailable" view;
  a network failure shows "Cannot reach the DealPilot API" with the start command.
- **Date range**: one range per page, kept in the URL, default = `dimensions.date_range`,
  validated before any request (start <= end, inside the dataset range).

### 5.1 Dashboard (`dashboard.png`)
| UI element | Endpoint and parameters | Fields used | Transformation |
|---|---|---|---|
| Date range picker | `/v1/dimensions` | `date_range.start`, `.end` | Bounds and default |
| Total sales card | `/v1/sales/metrics?start&end` | `totals.revenue` (per D5) | Decimal string to display text, for example `$12.5M` (exact value in a tooltip) |
| Orders card | same call | `totals.orders` | English number format |
| Products card | `/v1/dimensions` | `products[]` | Count; per D4, the number active on the range end, labeled "Active" |
| Customers card | `/v1/metadata` | `row_counts.customers` | Count, labeled "Customers in dataset": it does not follow the range, because the API has no customer metric |
| Change badges | second `/v1/sales/metrics` call for the comparison period (per D3) | `totals` | Percent change; hidden when D3 says so |
| Daily sales chart | `/v1/sales/metrics?start&end&group_by=date&interval=day` | `rows[].date`, measure per D5 | Fill every day of the range with 0 when missing; at most 1,096 points |
| Sales by region donut | `/v1/sales/metrics?start&end&group_by=region` + `/v1/dimensions` | `rows[].region_id`, measure, `regions[].name` | Share = row / total; regions without sales shown at 0%; names from the API |

Filters the API supports here: date range (used); `region_id`, `category`, `product_id`
(not used in F1, to match the design). **Removed from the design**: the "Expected demand"
line and legend entry, the user name and role, the notification bell, the search box.

### 5.2 Sales analysis (`seal.png`)
| UI element | Endpoint and parameters | Fields used | Transformation |
|---|---|---|---|
| Tabs | none | none | Overview, By product, By region; the URL holds the tab |
| Average sales per day (Overview) | `/v1/sales/metrics?start&end` | `totals` measure (D5) | Per D5: total / number of open days in the range (spec 001 section 8.1) |
| Top product (Overview) | `...&group_by=product` + dimensions | `rows[]` | Highest measure; ties broken by `product_id`; name from dimensions |
| Top region (Overview) | `...&group_by=region` + dimensions | `rows[]` | Highest measure; ties by `region_id` |
| Growth (Overview) | comparison call (D3) | `totals` | Per D3; hidden otherwise |
| Sales by product, top 10 (Overview) | `...&group_by=product` | `rows[]` | Sort by measure descending, then `product_id`; first 10 |
| Sales by month + year selector (Overview) | `/v1/sales/metrics?start&end&group_by=date&interval=month`, `start`/`end` = the chosen year clipped to the dataset range | `rows[].date` | 12 columns; months without rows = 0; months outside the dataset are not drawn; years = those in `date_range` |
| By product tab | `...&group_by=product`, optional `category`, `region_id` filters | `units`, `revenue`, `orders`, `order_lines` per product | Table of every product (0 when missing), sortable; a note that orders don't add up across products |
| By region tab | `...&group_by=region`, optional `category`, `product_id` filters | all four metrics per region | Table and bar chart; regions without sales at 0 |

Filters the API supports here: date range, `category`, `region_id`, `product_id` (the two
tabs offer category and region or product selectors fed by `/v1/dimensions`). **Removed
from the design**: the By customer and Promotion effects tabs (no contract).

### 5.3 Products (`product_custom.png`)
| UI element | Endpoint and parameters | Fields used | Transformation |
|---|---|---|---|
| All products table | `/v1/dimensions` + `/v1/sales/metrics?group_by=product` (dataset range) | `product_id`, `name`, `category`, `launch_date`, `discontinue_date`; `revenue` and `units` per product | Join by `product_id`; 0 for products without rows; sortable columns |
| Search box | none (client-side) | `product_id`, `name` | Case-insensitive contains |
| Category filter | none (client-side) | `categories[]` | "All" or one category |
| Status filter and column | none (client-side) | launch and discontinue dates | Per D4; hidden if D4 is not approved |
| Categories tab | `/v1/sales/metrics?group_by=category` | four metrics per category | Table with product count per category from dimensions |

**Removed from the design**: the Price column (`list_price` is not exposed, spec 002 D8),
the Performance tab (no contract), the "New product" button (read-only).

### 5.4 Data (`data_manage.png`)
| UI element | Endpoint and parameters | Fields used | Transformation |
|---|---|---|---|
| Overview table | `/v1/metadata` | `row_counts` | One row per table: icon, table name, row count; fixed order (regions, products, customers, promotions, orders, order_lines, expected_demand), then any other key alphabetically |
| Metadata tab | `/v1/metadata`, `/health` | `seed`, `start`, `end`, `generator_version`, `library_versions`, API `version` | Key-value list; `library_versions: null` shows "Not recorded" |

**Removed from the design**: file sizes and file dates (not in the API), the Tables tab
(no contract), the "Generate data" button (read-only API). The row count of
`expected_demand` may be shown (spec 002 section 5.2); its contents never are.

## 6. Business rules D3, D4 and D5 (approved 2026-11-01)

### 6.1 D3: "Change vs previous period" badges and Growth
**Question.** The designs show "+12.3%" on Total sales and Orders and a "Growth +12.3% vs
previous period" card. Compared with which period?

**What the API provides.** Totals for any range inside the dataset. A comparison needs a
second `/v1/sales/metrics` call; the API has no comparison feature, and the range can't
start before the dataset (`date_out_of_range`, never clipped).

**Alternatives.**
| Option | Rule | Trade-off |
|---|---|---|
| A | No comparison in F1 | Simplest; the design loses its badges |
| B | Previous period of the same length, ending the day before `start` (matches the design label "vs previous period") | Misleading on seasonal data (December against November looks like growth); not available for ranges starting within one range length of the dataset start, including the default full range |
| C | Same dates one year earlier ("vs same period last year"); Feb 29 maps to Feb 28 | Removes the yearly seasonality the generator builds in (spec 001 section 5); label differs from the design; not available for ranges in the first data year or for the default full range |
| D | A comparison field computed by the API | Changes the API contract (spec 002): out of scope |

In B and C, the badge is hidden when the comparison period is not fully inside the
dataset, and shows "n/a" when the comparison total is 0. Percent = (current - previous) /
previous, one decimal.

**Recommendation: C**, labeled "vs same period last year", because the synthetic data has
strong yearly and weekly patterns and C is the only option that doesn't report them as
growth. With the default full range, badges are hidden, so the default dashboard shows
none.
**Decision: approved 2026-11-01 by the user (option C).** The selected period is compared
with the same dates one year earlier; the comparison is hidden when that period is not
fully inside the dataset.
**Impact.** UI: one extra request per screen, a label change from the design, a "not
available" state. Backend: none.

### 6.2 D4: Product status ("Active") and the Products card
**Question.** The designs show a Status column ("Active"), a Status filter and "50
Active" on the Products card. What does "Active" mean, and on which date?

**What the API provides.** `launch_date` and `discontinue_date` (null when still sold) per
product. Spec 001 section 4: a product is active on day d when `launch_date <= d` and
(`discontinue_date` is null or `d < discontinue_date`).

**Alternatives.**
| Option | Rule | Trade-off |
|---|---|---|
| A | No status column, filter or "Active" label | Loses a design element |
| B | Status on a reference date: the range end on the Dashboard, the dataset end on Products. Values "Active", "Discontinued" (`discontinue_date <= ref`), "Not launched yet" (`launch_date > ref`) | Clear and exact; one rule everywhere |
| C | "Sold in the period" vs "No sales in the period", from the sales rows | Mixes lifecycle and sales; a product with zero sales in a short range would look inactive |

**Recommendation: B**, with the spec 001 section 4 rule. On the default dashboard (range
end 2025-12-31, seed 42 data) the card would read 47 of 50 active (3 products are
discontinued; checked read-only on `data/raw`, 2026-11-01).
**Decision: approved 2026-11-01 by the user (option B).** Status uses `launch_date` and
`discontinue_date` with the spec 001 section 4 rule, on the reference date defined here
(range end on the Dashboard, dataset end on Products).
**Impact.** UI: a status badge, a status filter, the "Active" card label. Backend: none
(client-side, from `/v1/dimensions`).

### 6.3 D5: Main sales measure and the daily average
**Question.** "Sales" in the designs is money ("$12.5M", "$482K"), but "Average sales per
day 34 247" has no unit. Which measure do cards and charts use, and how is a daily average
computed?

**What the API provides.** `revenue` (USD after discounts, exact decimal string), `units`,
`orders`, `order_lines`. Spec 001 section 8.1 defines a daily average over **open** days
(Dec 25 and Jan 1 left out).

**Alternatives.**
| Option | Measure | Daily average |
|---|---|---|
| A | Revenue everywhere | Revenue / open days in the range |
| B | Units everywhere (the forecasting target, spec 003) | Units / open days |
| C | Revenue by default, with a Revenue/Units toggle on charts | Per the selected measure / open days |
| (any) | | Alternative divisor: calendar days, or days with sales |

**Recommendation: A**, revenue in USD everywhere in F1 (it matches the designs), with the
open-day average of spec 001 section 8.1, labeled "Average revenue per day". Tables on the
Sales analysis tabs also show units, orders and order lines. A toggle (C) can come later.
**Decision: approved 2026-11-01 by the user (option A).** Revenue is the primary measure;
average daily revenue is computed over open days; units, orders and order lines stay
available in Sales analysis.
**Impact.** UI: one fixed measure, the closed-day constants (Dec 25, Jan 1, spec 001
section 5.7) duplicated in the frontend for the divisor and tested against the spec.
Backend: none.

## 7. Functional requirements
- FR-01 Every value shown comes from a spec 002 response or a transformation listed in
  section 5. Sample values from the designs are never hard-coded; nothing is fabricated.
- FR-02 Money stays a decimal string from the API to the display formatter. Totals shown
  are the API totals, never client sums; shares and percents are computed for display
  only.
- FR-03 Date series are completed with 0 for missing buckets (spec 002 D5), using the
  bucket rules of spec 002 section 5.4 (ISO weeks start Monday; months on the 1st).
- FR-04 No request can exceed 20,000 groups: daily data is never grouped by product or
  category; product groups are never combined with daily dates.
- FR-05 Requests use only documented parameters, repeated keys for lists, and validated
  dates; a request is never sent with a range outside `date_range`.
- FR-06 English error messages by code: `data_unavailable` "The dataset is not available.
  Generate it, then reload."; `result_too_large` "This view asks for too much data.
  Choose a shorter range or fewer groups."; `date_out_of_range`, `invalid_date`,
  `invalid_date_range` "The selected dates are outside the dataset or not valid.";
  `invalid_filter` "A selected filter value is no longer in the dataset."; others
  "Something went wrong. Try again." The API `message` may be shown as a detail; paths
  are never shown.
- FR-07 State lives in the URL (range, tab, filters, year) so a view can be bookmarked and
  reloaded; nothing is stored in the browser (D7).
- FR-08 Concurrent requests for one view are cancelled when the range changes, so an old
  answer never overwrites a new one.

## 8. Language
English only (`AGENTS.md`, permanent product rule, unchanged). The designs are in French;
F1 keeps their layout and uses these English texts (D8 approves the wording). Strings live
in one module, so AC-UI-11 can check them.

| French (design) | English (proposed) |
|---|---|
| Tableau de bord | Dashboard |
| Données | Data |
| Analyse / Analyse des ventes | Analysis / Sales analysis |
| Prévisions / Prévisions de ventes | Forecasts / Sales forecasts |
| Promotions | Promotions |
| Produits | Products |
| Régions | Regions |
| Clients | Customers |
| Rapports | Reports |
| Paramètres | Settings |
| Rechercher... | Search... |
| Administrateur | Administrator |
| Aperçu des ventes, des promotions et des prévisions | Overview of sales, promotions and forecasts (F1: "Overview of sales", since F1 has no promotions or forecasts) |
| Ventes totales | Total sales |
| Commandes | Orders |
| Actifs / Actif | Active |
| Ventes quotidiennes | Daily sales |
| Ventes réelles | Actual sales |
| Demande attendue | Expected demand (not shown in F1) |
| Ventes par région | Sales by region |
| Ventes | Sales |
| Jeux de données et génération de données synthétiques | Datasets and synthetic data generation (F1: "Dataset overview", since F1 cannot generate data) |
| Générer des données | Generate data (not shown in F1) |
| Vue d'ensemble | Overview |
| Tables | Tables |
| Métadonnées | Metadata |
| régions, produits, clients, commandes, lignes | regions, products, customers, orders, lines |
| Explorez les tendances et les performances | Explore trends and performance |
| Par produit / Par région / Par client | By product / By region / By customer |
| Effet des promotions | Promotion effects |
| Ventes moyennes/jour | Average sales per day (per D5: "Average revenue per day") |
| Meilleur produit / Meilleure région | Top product / Top region |
| Croissance / vs période précédente | Growth / vs previous period (per D3) |
| Ventes par produit (Top 10) | Sales by product (top 10) |
| Ventes par mois | Sales by month |
| Liste des produits et performances | Product list and performance |
| Nouveau produit | New product (not shown in F1) |
| Tous les produits / Catégories / Performance | All products / Categories / Performance |
| Rechercher un produit... | Search products... |
| Catégorie / Statut / Toutes / Tous | Category / Status / All / All |
| Nom du produit / Prix / Ventes (total) | Product name / Price / Sales (total) |
| Modèles et résultats de prévision | Forecasting models and results |
| Modèle actuel / Nouvelle prévision | Current model / New forecast |
| Prévision / Comparaison / Paramètres | Forecast / Comparison / Settings |
| Prévisions vs Ventes réelles | Forecast vs actual sales |
| Intervalle de confiance | Confidence interval |
| Métriques de performance (période de test) | Performance metrics (test period) |
| Meilleur que Naive / Bon / Unités / Biais | Better than naive / Good / Units / Bias |
| Analyse de l'impact des promotions | Promotion impact analysis |
| Nouvelle promotion / Calendrier / Analyse d'impact | New promotion / Calendar / Impact analysis |
| Produit / Région / Type / Début / Fin | Product / Region / Type / Start / End |
| Lift attendu / Remise | Expected lift / Discount |
| Terminée / Planifiée | Ended / Scheduled |
| Rapports et exportation des données | Reports and data export |
| Nouveau rapport / Rapports prédéfinis / Exportation | New report / Predefined reports / Export |
| Rapport de ventes | Sales report |
| Résumé des ventes par période, produit et région | Sales summary by period, product and region |
| Analyse des promotions / Impact des promotions sur les ventes | Promotion analysis / Impact of promotions on sales |
| Performance des prévisions / Métriques de précision des modèles | Forecast performance / Model accuracy metrics |
| Rapport complet / Analyse complète du jeu de données | Full report / Full dataset analysis |
| Générer | Generate |
| Bienvenue / Connectez-vous à votre compte | Welcome / Sign in to your account |
| Mot de passe / Votre mot de passe | Password / Your password |
| Se souvenir de moi / Mot de passe oublié ? | Remember me / Forgot password? |
| Se connecter | Sign in |
| Pas encore de compte ? Créer un compte | Don't have an account? Create one |
| Données synthétiques réalistes | Realistic synthetic data |
| Prévisions de ventes fiables | Proposed: "Forecasts measured against a baseline" (a literal "Reliable sales forecasts" is a claim the product can't support yet, D8) |
| Décisions basées sur les données | Data-driven decisions |
| Janv., Févr., Avr., Mai, Juin, Juil., Août, Déc. | Jan, Feb, Apr, May, Jun, Jul, Aug, Dec |

Formats are English: `$12.5M`, `$482K`, `152,840`, `-1.2%`, `Jan 1, 2024`. Product,
category and region names are shown exactly as the API returns them.

## 9. Visual fidelity
The four screenshots are the visual reference; they are not modified. Each page keeps its
reference layout, with English text and with the removed elements of section 5 leaving no
empty placeholder (the space closes up; a page header with no action button keeps its
title block only).

| Screen | Layout to reproduce |
|---|---|
| Shell | Fixed left sidebar (logo top left, icon + label items, active item filled blue), top bar (search box removed; right side empty in F1), content on a dark navy background |
| Dashboard | Header: title and subtitle left, date range picker right. Row of 4 KPI cards (square blue icon left, label, large value; badge or "Active" right). Second row: "Daily sales" line chart card about two-thirds wide with a legend top right; "Sales by region" donut card one-third wide with the total in the center and a legend with dots and percentages |
| Sales analysis | Header with date range picker. Pill tabs (active tab filled). Row of 4 KPI cards. Two charts side by side: horizontal bars "Sales by product (top 10)" with values at the bar ends; vertical columns "Sales by month" with a year selector in the card header |
| Products | Header. Pill tabs. Filter row: search box left, Category and Status selects right (labels above). Table with a header row, ID, Product name, Category, Sales (total), Status (green pill) |
| Data | Header. Pill tabs. Table with a file icon per row, table name, row count |

Visual tokens are measured from the images with a color picker during implementation
and stored in one tokens file; the current reading is: background deep navy, cards a
lighter navy with a thin border and about 12 px radius, primary blue for buttons, active
items and the main series, orange for a second series, green for positive badges, white
headings and muted gray-blue secondary text, a geometric sans-serif typeface (D10).
Fidelity is checked per AC-UI-14.

**Visual identity update (2026-11-02, product owner's approval).** The product owner approved a
premium black and electric-blue identity with liquid-glass surfaces, refined the same day
("liquid blue"): deep black #020711, black-navy #030D1D, midnight blue #071B35, glass panels
rgba(5, 22, 45, 0.82), electric blue #087CFF, bright blue #008BFF, cyan #00C8FF, light cyan
#56E5FF, text #F5F9FF and #A9BCD5, borders rgba(70, 150, 255, 0.25); region colors on the
donut: blue, cyan, yellow, orange and pink, so the five regions stay distinct; translucent gradient surfaces with a fine luminous edge and a
soft top reflection; glow and gradients used sparingly (selected navigation, primary
buttons, chart line). It replaces the colors read from the reference images; the layouts
of the reference images stay the structure of each screen, and the original images are
unchanged. It is implemented as shared design tokens (`frontend/src/styles/tokens.css`),
first on the Dashboard; the other three screens get their final styling after the product
owner's visual approval. It changes no data, calculation, API, route or behavior.

## 10. Responsive behavior
- Desktop (1280 px and wider): the reference layout, sidebar always visible.
- Tablet (768 to 1279 px): the sidebar collapses to icons with labels on hover and focus;
  KPI cards on two columns; the two charts of a row stack full width.
- Phone (below 768 px): the sidebar becomes a menu button; one column; tables scroll
  horizontally inside their card, never the page; the date range picker uses native date
  inputs.
- Accessibility: keyboard use and visible focus on every control; text contrast at least
  WCAG AA; each chart has a title and a text alternative (a hidden data table).

## 11. Security
- Local use only, like the API (spec 002 section 2): the dev server and the release
  server listen on `127.0.0.1`. No authentication in F1 (D1, approved). Neither the
  unauthenticated application nor the API may be exposed publicly or on a network; any
  use beyond one local machine needs an authentication spec first.
- Same origin for pages and API (D9); the API keeps sending no CORS headers.
- No secrets, keys or AI provider settings in the frontend, its build or its environment
  files; no call to Gemini, Meta or any external service; no analytics or tracking; no
  external fonts or CDNs at run time.
- React escaping only: no raw HTML injection (`dangerouslySetInnerHTML` is not used).
- Content Security Policy for the built app: `default-src 'self'`, no inline scripts, no
  `eval`.
- Dependencies: exact versions in `frontend/package-lock.json` with integrity hashes;
  installs with `npm ci`; `npm audit` reviewed; licenses of the whole tree reviewed before
  approval; install scripts reviewed (some build tools download native binaries).
- No personal data: the design shows a person's name in the top bar; F1 shows none.

## 12. Technical architecture

### 12.1 Options considered
| Option | For | Against |
|---|---|---|
| A. React + Vite + TypeScript single-page app in `frontend/` | Already the stack in `AGENTS.md`; Node 24 present (24.21.0, npm 11.19.0); fast dev server with a built-in proxy; static build; strong typing of the spec 002 responses | A new Node dependency tree to approve and audit |
| B. Pages rendered by FastAPI (Jinja2) | Python only; same origin | New Python dependency; charts still need JavaScript; changes the API app (spec 002) |
| C. Plain HTML and JavaScript, no build | No dependencies | Hard to keep four screens consistent and tested; no type checks |
| D. A React meta-framework (for example Next.js) | Routing and rendering built in | Needs a Node server; far more than a local read-only app needs |

**Recommendation: A.** It matches the repository's stated stack, keeps the backend
unchanged, and the build output is static files.

### 12.2 Project structure
```
frontend/
  package.json, package-lock.json, tsconfig.json, vite.config.ts, index.html
  src/
    main.tsx, App.tsx            entry, shell, routes
    api/                         client.ts (fetch, query strings, errors), types.ts
                                 (spec 002 response types), endpoints.ts (4 functions)
    domain/                      money.ts, dates.ts (buckets, open days), status.ts (D4),
                                 comparison.ts (D3), measures.ts (D5)
    components/                  layout, KpiCard, Card, Tabs, DateRangePicker, Select,
                                 SearchBox, DataTable, StatusBadge, charts/, states/
    pages/                       Dashboard, SalesAnalysis, Products, DataPage, NotFound,
                                 DataUnavailable
    text/en.ts                   every user-facing string
    styles/                      tokens.css, global.css (+ CSS modules next to components)
  tests/
    unit/                        domain and API client (Vitest)
    components/                  pages with recorded API fixtures (Testing Library)
    e2e/                         browser checks against the real API (Playwright, D13)
```
The backend, the API and the Python lockfiles are not touched. `.gitignore` already
ignores `node_modules/` and `frontend/dist/`.

### 12.3 API client
One module wraps `fetch`: base path `/v1` (same origin), query strings with repeated keys,
JSON parsing, and a typed `ApiError {status, code, message}` built from the spec 002
error body; network failures become a distinct error. Four functions, one per endpoint,
return typed responses. Money stays a string type. No retries (the API is local and
deterministic). Fixture responses for tests are recorded once from the API on seed 42
data and stored as JSON in `tests/`.

### 12.4 State management
No state library. The URL (range, tab, filters, year) is the source of truth; React state
holds request status; a small `useApi` hook runs a request with an `AbortController`
(FR-08) and keeps an in-memory cache per page load, keyed by request URL. `/v1/dimensions`
and `/v1/metadata` are loaded once per page load. Nothing is persisted (D7).

### 12.5 Charts
Four chart types: line (daily sales), donut (sales by region), horizontal bars (top 10),
vertical columns (sales by month).
| Option | For | Against |
|---|---|---|
| Recharts | React components, SVG (crisp, testable), covers all four types, MIT | One more dependency tree |
| Apache ECharts | Rich, canvas, close to the designs' smooth lines | Large bundle; canvas is harder to test and to make accessible |
| Hand-drawn SVG | No dependency | More code to write, test and keep accessible |

**Decision D12 (approved 2026-11-01): hand-drawn SVG.** Recharts and `react-is` are not
added. Every chart is accessible (title, text alternative, keyboard focus on data points
with tooltips), responsive (redrawn to its container width) and covered by tests.
Colors and fonts come from the tokens file. Rationale: Recharts and its peer `react-is`
would have brought 41 of the 48 packages shipped to the browser (Redux, Immer, eleven d3
modules and their types); four simple chart types don't justify that.

### 12.6 Styling
CSS Modules (built into Vite, no dependency) plus CSS custom properties for the design
tokens; no CSS framework. One global stylesheet for the reset, fonts and tokens.

### 12.7 Serving and same origin
Development: Vite dev server on `127.0.0.1` with a proxy from `/v1` and `/health` to the
API on `127.0.0.1:8000`. Local release: `vite preview` (part of Vite, no extra
dependency) on `127.0.0.1` with the same proxy, serving the static build. Serving the
build from FastAPI would change spec 002 (404 behavior outside `/v1`) and is not proposed
(D9).

### 12.8 Testing strategy
- **Unit (Vitest)**: money formatting, bucket filling (days, ISO weeks, months), open-day
  counting against spec 001 section 5.7, D3/D4/D5 rules, query-string building, error
  mapping.
- **Components (Vitest + Testing Library + jsdom)**: each page with recorded fixtures:
  loading, ready, empty, error and 503 states; that no out-of-scope control is rendered.
- **End to end (Playwright, D13)**: the real API on generated seed 42 data in a temporary
  folder: AC-UI-01 to AC-UI-10, responsive widths (AC-UI-13), screenshots for the
  fidelity review (AC-UI-14).
- **Lint and types**: `tsc --noEmit` and ESLint with React hooks rules, run with the
  tests. The Python suite stays as it is; a frontend change never changes it.
- Commands are listed in the frontend README when F1 is implemented.

### 12.9 Dependency installation proposal (final, not authorized)
Nothing is installed. The tree below uses only the options approved on 2026-11-01 (D10
Inter, D11 `react-router`, D12 SVG charts with no Recharts and no `react-is`, D13
Playwright). It was resolved read-only on 2026-11-01: registry metadata (`npm view`) and
`npm install --package-lock-only --ignore-scripts` in a temporary folder outside the
repository; no `node_modules` was created, no install script ran, and no project file or
lockfile changed. Resolution had no peer-dependency conflict. Resolved lockfile SHA-256:
`cda61a25d548924357592cf0d576f6b938bd9705cb2dc809299754a018a62095` (it is regenerated in
`frontend/` at installation and compared).

**Version rule.** The newest stable release published at least 14 days earlier (on or
before 2026-10-18), to lower supply-chain risk. TypeScript stays at 6.0 because
`typescript-eslint` 8.71.2 supports `typescript` below 6.1 only.

**Node.** Every package accepts Node 24.21.0 (installed). The strictest requirement is
`jsdom` (`^22.22.2 || ^24.15.0 || >=26.0.0`).

**Direct packages (19).**

| Package | Version | Published | License | Section | Why it is needed | Replaceable by |
|---|---|---|---|---|---|---|
| `react` | 19.3.1 | 2026-10-14 | MIT | dependencies | UI library (approved architecture) | none |
| `react-dom` | 19.3.1 | 2026-10-14 | MIT | dependencies | Renders React in the browser | none |
| `react-router` | 8.4.0 | 2026-09-15 | MIT | dependencies | Page and tab URLs (D11) | Hand-written routing (not chosen) |
| `@fontsource/inter` | 5.3.0 | 2026-07-19 | OFL-1.1 | dependencies | Self-hosted Inter (D10) | System font stack (not chosen) |
| `vite` | 8.3.4 | 2026-10-08 | MIT | devDependencies | Dev server, proxy, build, preview (D9) | none |
| `@vitejs/plugin-react` | 6.1.2 | 2026-10-05 | MIT | devDependencies | JSX and fast refresh for Vite | none |
| `typescript` | 6.0.3 | 2026-04-16 | Apache-2.0 | devDependencies | Type checking (approved architecture) | none |
| `@types/react` | 19.3.0 | 2026-09-09 | MIT | devDependencies | React types | none |
| `@types/react-dom` | 19.3.0 | 2026-09-09 | MIT | devDependencies | React DOM types | none |
| `vitest` | 5.0.5 | 2026-10-15 | MIT | devDependencies | Unit and component tests | Node's test runner (no JSX, no DOM) |
| `@testing-library/react` | 16.3.3 | 2026-08-27 | MIT | devDependencies | Render pages in tests | Manual rendering |
| `@testing-library/dom` | 10.4.2 | 2026-09-13 | MIT | devDependencies | Required peer of the line above | none |
| `@testing-library/user-event` | 14.6.8 | 2026-10-13 | MIT | devDependencies | Realistic clicks and typing | `fireEvent` |
| `jsdom` | 30.1.3 | 2026-10-15 | MIT | devDependencies | Browser environment for Vitest | none for component tests |
| `@playwright/test` | 1.64.1 | 2026-10-14 | Apache-2.0 | devDependencies | End-to-end and screenshot tests (D13) | none (approved) |
| `eslint` | 10.13.0 | 2026-10-16 | MIT | devDependencies | Lint, as ruff does for Python | `tsc` alone |
| `@eslint/js` | 10.0.1 | 2026-02-06 | MIT | devDependencies | Recommended rules | none while ESLint is kept |
| `typescript-eslint` | 8.71.2 | 2026-10-12 | MIT | devDependencies | ESLint for TypeScript | none while ESLint is kept |
| `eslint-plugin-react-hooks` | 7.1.1 | 2026-04-17 | MIT | devDependencies | Rules of hooks | none while ESLint is kept |

**Whole tree (lockfile v3).** 253 packages: 19 direct and 234 transitive.
- **Shipped to the browser: 7 packages**: `react`, `react-dom`, `scheduler`,
  `react-router`, `cookie-es`, `@remix-run/route-pattern` (all MIT) and the Inter font
  files (OFL-1.1). Everything else runs only at build or test time.
- **Platform packages:** 27 optional builds for various systems; on Windows x64 only 2
  are used: `@rolldown/binding-win32-x64-msvc` 1.2.16 (MIT, Vite's bundler) and
  `lightningcss-win32-x64-msvc` 1.33.0 (MPL-2.0, Vite's CSS tool).
- **Install scripts:** only `fsevents` 2.3.3 (macOS only, never installed on Windows).
  No other package runs code at installation; Playwright downloads browsers only with
  its own command (below).
- **Deprecated packages:** none. **Several versions of one package** (normal in npm,
  development only): `lru-cache`, `eslint-visitor-keys`, `ignore`, `semver`, `hookified`.

| License | Packages | In the browser? | Where it comes from |
|---|---|---|---|
| MIT | 189 | 6 | React, router, Vite, Vitest, Testing Library, ESLint and most helpers |
| Apache-2.0 | 21 | no | TypeScript, Playwright, ESLint internals, `aria-query`, `detect-libc` |
| MPL-2.0 | 12 | no | `lightningcss` and its platform builds |
| ISC | 11 | no | `semver`, `picocolors`, `saxes`, `which` and similar |
| BSD-2-Clause | 8 | no | `espree`, `eslint-scope`, `entities`, `uri-js` and similar |
| BSD-3-Clause | 3 | no | `esquery`, `source-map-js`, `tough-cookie` |
| BlueOak-1.0.0 | 4 | no | `lru-cache`, `minimatch` |
| MIT-0 | 2 | no | `@csstools` color helpers |
| CC-BY-4.0 | 1 | no | `caniuse-lite` (browser support data, build time) |
| CC0-1.0 | 1 | no | `mdn-data` |
| OFL-1.1 | 1 | yes | `@fontsource/inter` |

**License compatibility.** All licenses are permissive or weak copyleft; there is no GPL,
AGPL or LGPL, and none limits internal use. The browser bundle holds MIT code and the
OFL-1.1 font only. MPL-2.0 (`lightningcss`) is file-level copyleft that applies only to
its own files if they are changed and distributed; it runs at build time and is not
bundled. CC-BY-4.0 (`caniuse-lite`) asks for attribution of a data set used at build
time. OFL-1.1 allows bundling the font with the app; the font may not be sold on its own,
its name and copyright stay, and its license file ships with it. If the frontend is ever
distributed outside the team, the MIT notices and the OFL license must ship with it.
These conditions are separate from the D29 conditions of spec 003 (pygit2 only).

**Playwright browser binaries (tracked separately, D13; not authorized).** `@playwright/test`
1.64.1 does not download browsers when installed. Browsers are installed by a separate
command (`npx playwright install chromium`), into the user's Playwright cache outside the
repository (about 150 MB for Chromium). They have their own licenses (Chromium: BSD-3-Clause
with third-party notices) and need their own authorization, listed with the exact build
when requested.

**Installation steps, once authorized.**
1. Create `frontend/package.json` with exactly these 19 versions (no ranges).
2. Run `npm install --ignore-scripts` once to create `frontend/package-lock.json`, check
   that its tree matches this section (same packages, versions and licenses), then use
   `npm ci --ignore-scripts` from then on.
3. Report `npm audit` and a license listing of the lockfile.
4. Never touch the Python lockfiles; `node_modules/` stays gitignored.

**Installation record (2026-11-01, user's explicit authorization).**
- Tools: Node 24.21.0, npm 11.19.0.
- `frontend/package.json` holds exactly the 19 versions above (no ranges), with
  `engines.node >=24.15.0`. Command, from `frontend/`: `npm install --ignore-scripts`:
  228 packages added (the 253-entry tree minus 25 optional builds for other systems); no
  lifecycle script ran.
- `frontend/package-lock.json` (lockfile v3) matches the reviewed tree: all 253 package
  entries identical, root dependencies identical, 0 added, removed or changed. Its SHA-256
  is `66d66150b82765c92488e9c063c39ac6ea5a7fef1c1eb5a21bbc2e90b8b58909`; it differs from
  the reference `cda61a25...062095` only by the project's own name, version, description
  and `engines`; with those swapped into the reference, the two files are identical.
- `npm ls --all`: no missing, invalid or extraneous package; every installed version
  equals the lockfile.
- Installed licenses (228): MIT 174, Apache-2.0 21, ISC 11, BSD-2-Clause 8, BlueOak-1.0.0
  4, BSD-3-Clause 3, MPL-2.0 2 (`lightningcss` and its Windows build), MIT-0 2, CC-BY-4.0
  1, CC0-1.0 1, OFL-1.1 1 (Inter, with its `LICENSE` file). Six packages declare their
  license in `package.json` but ship no license file (`@humanfs/types`,
  `@rolldown/binding-win32-x64-msvc`, `esrecurse`, `imurmurhash`,
  `natural-compare`, `saxes`); all are development-only and not bundled.
- `npm audit`: 11 moderate, 0 high, 0 critical, all from one advisory,
  GHSA-g3hv-75wg-m249 (`minimatch` below 11.0.1, denial of service through glob
  patterns), reached through `eslint` and `typescript-eslint` (installed `minimatch`
  10.2.6). Development and lint only; nothing in the browser bundle; lint reads the
  project's own files. npm's suggested "fixes" are major downgrades (for example `eslint`
  4.0.0, `typescript-eslint` 8.14.0), so none was applied; a fix needs a new approved
  version when `eslint` ships one.
- Checks: `tsc` 6.0.3, `vite` 8.3.4, `vitest` 5.0.5, `eslint` 10.13.0, `playwright`
  1.64.1 all start; `tsc --noEmit --strict` on the React and React DOM type definitions
  passes; `react` 19.3.1 and `react-router` import in Node. No Playwright browser was
  downloaded (no `ms-playwright` cache exists).

## 13. Implementation order (after approval)
1. Scaffold `frontend/` with the approved dependencies, the API client, tokens and shell.
2. Data page (simplest: two endpoints, no charts).
3. Products page.
4. Dashboard.
5. Sales analysis.
6. End-to-end, responsive and fidelity checks; documentation; roadmap update.
Each step ends with the frontend tests, the Python suite (unchanged) and a report.

**Implementation record (2026-11-01, user's authorization).** Built in `frontend/` with
the approved dependencies only: `src/api` (typed client for the four endpoints, error
mapping), `src/domain` (money as exact cents, UTC dates, the D3, D4 and D5 rules),
`src/hooks` (requests with cancellation and a per-load cache, URL state, element width),
`src/components` (shell, cards, tabs, table, date range, hand-drawn SVG charts),
`src/pages` (the four screens and "Page not found"), `src/text/en.ts` (every string),
`src/styles` (tokens and global styles). Checks on 2026-11-01: `tsc` strict, ESLint and
Vitest (42 tests: unit and page tests against a fake spec 002 API) pass; the build
carries the CSP and the Inter license. D9 was verified live: through the dev server and
`vite preview` every request is same-origin, all three servers listen on `127.0.0.1`
only, and no response carries a CORS header (Vite's own CORS is turned off,
`cors: false`). Not yet verified: AC-UI-13 and AC-UI-14 (responsive widths and visual
fidelity in a real browser) and the end-to-end form of AC-UI-01 to AC-UI-10, which need
Playwright browsers (not authorized).

**Completion of the three modules (2026-11-02, product owner's authorization).** Sales
analysis, Products and Data use the shared liquid-blue design system, aligned with the
product owner's reference image `DealDesign/Tableau de bord futuriste DealPilot AI.png`
(two-tone titles, solid blue icon tiles, an icon before card titles, corner light on
cards, flowing light waves). Presentation changes only, on the same four endpoints: a round
axis scale (steps of 1, 2, 4 or 8 times a power of ten), the year selector inline with the
"Sales by month" title, a "Showing N of M products" count that follows the filters, and on
the Data page four summary cards (seed with generator version, dataset period in days
computed from `start` and `end`, number of tables, API version and status from
`/health`) and the metadata shown as a table. No new metric, calculation, endpoint, data or
dependency. Checks on 2026-11-02: `tsc`, ESLint, Vitest (45 tests) and the build pass; in
headless Chrome (local, no download) every view at 1440, 1270, 1024 and 390 px has no
horizontal overflow and no console error. Still not verified: AC-UI-13 and AC-UI-14 as
automated Playwright checks (browsers not authorized).

**Release candidate QA (2026-11-02).** Results in `docs/release-candidate.md`: every route
loads directly and after a refresh with no console error (after adding a local SVG
favicon); interactions checked in the local Chrome (date range, tabs, filters, year,
search, sorting); displayed figures equal an independent DuckDB computation from
`data/raw`; no CORS and local-only binding confirmed; no horizontal overflow at 1440, 1270,
1024 and 390 px. The spec stays Draft.

**RC1 visual acceptance (2026-11-02, product owner).** The product owner accepted the
visual rendering of the four modules for a local seed 42 demonstration. This is not an
approval of this spec, which stays Draft until the product owner approves it explicitly.
Defect fixed after acceptance: the By region table now fits from 1280 px (chart and table
share the row 3:4). Closure record: `docs/release-candidate.md`.

**Approval record (2026-11-02, product owner's explicit decision).** The spec is approved
for the RC1 scope already implemented and visually accepted on 2026-11-02, then marked
Implemented. Scope of the approval: the four modules of section 3.1 and their documented
read-only, local-only behavior. Excluded: the future pages of section 3.2, any API or
spec 002 change, and production capabilities (authentication, multi-company isolation,
public or cloud deployment). AC-UI-13 and AC-UI-14 were verified with the local Chrome
and the product owner's visual review, not with automated Playwright tests. The npm
advisory GHSA-g3hv-75wg-m249 (development tooling only) is accepted for the local RC1
environment; a separately approved remediation is required before public deployment.

## 14. Acceptance criteria (proposed)
Tests go in `frontend/tests/` and are named after the criterion (`AC-UI-NN`).

| ID | Criterion |
|---|---|
| AC-UI-01 | Given the API on seed 42 data, when the Dashboard opens with the default range, then Total sales shows `totals.revenue` and Orders shows `totals.orders` of `GET /v1/sales/metrics` with no parameters, in English formats, and the exact revenue string is available in the tooltip. |
| AC-UI-02 | The Products card shows the count of `/v1/dimensions` products (per D4: active on the range end); the Customers card shows `row_counts.customers` and does not change with the range. |
| AC-UI-03 | The daily chart has one point per day of the range; days missing from the response (closed days included) are 0. |
| AC-UI-04 | The region donut lists every region of `/v1/dimensions` by name; shares add up to 100% within display rounding. |
| AC-UI-05 | Sales analysis top 10 equals the 10 highest-revenue rows of `group_by=product` (ties by `product_id`), with names from `/v1/dimensions`. |
| AC-UI-06 | Sales by month shows 12 columns for a full year, 0 for months without sales; the year selector lists exactly the years in `date_range`. |
| AC-UI-07 | The Products table lists every product of `/v1/dimensions`, products without sales at 0; search and the category filter narrow it without a new request. |
| AC-UI-08 | The Data page shows every `row_counts` entry and the metadata fields of `/v1/metadata`, never `parameters`, never file contents of `expected_demand`. |
| AC-UI-09 | No request groups daily dates with products or categories; a mocked `result_too_large` shows the error state of that card only. |
| AC-UI-10 | A 503 `data_unavailable` shows the "Data unavailable" view without any path; a network failure shows the API start command. |
| AC-UI-11 | Every user-facing string comes from `text/en.ts`, and none of the French texts of section 8 that differ from their English equivalent (for example "Tableau de bord", "Ventes", "Commandes") appears in the built UI. |
| AC-UI-12 | In both the Vite development server and `vite preview` on `127.0.0.1`, every API request goes to the page's own origin through the proxy; no request needs CORS, and the spec 002 CORS test is unchanged and passes (D9). |
| AC-UI-13 | At 1440, 1024 and 390 px wide, no page scrolls horizontally, and the sidebar follows section 10. |
| AC-UI-14 | Each F1 page at 1440 px with seed 42 data is compared with its reference image by a person and a screenshot check; differences in layout, colors, spacing or components are listed and fixed, except the content differences required by sections 3 and 5. |
| AC-UI-15 | No out-of-scope control is rendered: write buttons, sign-in, notifications, search box, user name, expected demand, Price column, By customer and Promotion effects tabs. |
| AC-UI-16 | Per D3: the comparison badges appear only when the comparison period lies fully inside the dataset, and their percent equals (current - previous) / previous of two independent API calls. |
| AC-UI-17 | Per D5: Average revenue per day equals `totals.revenue` / open days in the range, open days counted independently with spec 001 section 5.7. |
| AC-UI-18 | Per D4: for seed 42 data at 2025-12-31, status counts match an independent count from `/v1/dimensions` with the spec 001 section 4 rule. |

## 15. Decision register
Approved on 2026-11-01 by the user: D3 (option C), D4 (option B), D5 (option A), see
section 6, and the eleven decisions below, each with the condition in "Approval". In the
last column, API means it changes an API contract, Dep that it adds a dependency,
Behavior that it changes what the product does or shows.

| ID | Approval (2026-11-01, user's explicit decision) |
|---|---|
| D1 | Approved: no sign-in in F1; local use only; neither the app nor the API may be exposed publicly |
| D2 | Approved: tabs without an approved API contract are hidden |
| D6 | Approved: the menu shows only the four implemented screens |
| D7 | Approved: range, tab, filters and year live in the URL; no local preference storage |
| D8 | Approved: the section 8 wording, including "Forecasts measured against a baseline"; no unsupported reliability claim about forecasts |
| D9 | Approved: Vite proxy in development and `vite preview` on `127.0.0.1`; both must be verified same-origin with no API CORS change (AC-UI-12) |
| D10 | Approved: self-hosted Inter through `@fontsource/inter`, keeping its OFL-1.1 license |
| D11 | Approved: `react-router`, subject to the exact tree and version review (section 12.9) |
| D12 | Approved: hand-drawn SVG charts; no Recharts and no `react-is`; charts accessible, responsive and tested |
| D13 | Approved: Playwright for end-to-end and screenshot tests; the package and the browser binaries are tracked separately; downloading browsers is not authorized yet |
| D14 | Approved: every screen beyond F1 needs its own approved spec and data contract |

The analysis presented for the decisions:

| ID | Question | Proposed implementation | Alternatives | Recommendation | Consequences | API / Dep / Behavior |
|---|---|---|---|---|---|---|
| D1 | Does F1 have sign-in? | No sign-in; local-only like the API (`127.0.0.1`) | A login screen backed by a new authentication spec | No sign-in in F1 | Business: anyone using the machine can read the synthetic data, as with the API today; `login.png` waits for its own spec. Technical: no session or password handling | No / No / Yes (no login screen) |
| D2 | What happens to tabs without a contract (By customer, Promotion effects, Products Performance, Data Tables)? | Hidden | Shown disabled with "Not available yet" | Hidden | Business: fewer visible features than the designs. Technical: no dead controls to test | No / No / Yes |
| D6 | What happens to sidebar items without a screen (Forecasts, Promotions, Regions, Customers, Reports, Settings)? | Hidden | Shown disabled with "Not available yet" | Hidden | Business: the menu shows 4 of the 10 design items. Technical: simpler navigation; items return with their specs | No / No / Yes |
| D7 | Are preferences remembered in the browser? | No; the URL holds range, tab, filters and year | Local storage for the last range and tab | No | Business: a bookmark or link restores a view; a new tab starts from the defaults. Technical: no stored data to version or clear | No / No / Yes |
| D8 | Is the English wording of section 8 approved? | The section 8 table, with "Forecasts measured against a baseline" and the F1 subtitles "Overview of sales" and "Dataset overview" | Literal translations of every design text | The table as proposed | Business: no claim the product can't support. Technical: one string file | No / No / Yes (visible text) |
| D9 | How do pages and API share one origin? | Vite proxy in development; `vite preview` with the same proxy on `127.0.0.1` for local releases | FastAPI serves the build (changes spec 002); CORS on the API (reverses a tested security rule) | Vite proxy and preview | Business: two local processes to start (API and frontend). Technical: no API change; `vite preview` is for local use, not public hosting | No / No (part of Vite) / No |
| D10 | Which typeface? | Self-hosted Inter (`@fontsource/inter` 5.3.0, OFL-1.1) | System font stack (Segoe UI on Windows) | Inter | Business: closer to the designs. Technical: font files in the bundle with their license | No / Yes (1 package) / No |
| D11 | Router library or hand-written routing? | `react-router` 8.4.0 | Hand-written routing on the History API for 4 pages and their tabs | `react-router` | Business: none. Technical: tested URL handling for tabs and filters; 3 extra runtime packages, all MIT | No / Yes / No |
| D12 | Chart library or hand-drawn SVG? | Hand-drawn SVG components (line, donut, horizontal bars, columns) | Recharts 3.10.1 (MIT; 41 runtime packages with its peer); ECharts (Apache-2.0, canvas, large) | Hand-drawn SVG | Business: the same charts; tooltips and legends written in-house. Technical: more code to write and test, but 41 fewer packages in the browser and full control of the look | No / No (Recharts: Yes) / No |
| D13 | Use Playwright for end-to-end and screenshot checks? | `@playwright/test` 1.64.1 plus a Chromium download | Component tests only, plus a manual fidelity review | Playwright | Business: AC-UI-13 and AC-UI-14 checked automatically. Technical: about 150 MB browser download outside the repository; 3 development packages | No / Yes (plus browser binaries) / No |
| D14 | When do pages beyond F1 come? | Each after its data contract exists (for example spec 003 D11 for forecasts), in its own spec or amendment | Build them now with placeholder data | Contract first | Business: no page shows invented or unapproved data. Technical: no throwaway screens | Not for F1 (later pages may need API changes, each approved separately) / No / Yes |

## 16. Amendment, 2026-11-04: Prediction screen (D14)

**Decision (product owner, 2026-11-04).** The Prediction page is approved as a new screen
under D14. Its data contract is `GET /v1/forecasts` (spec 003 section 10, D11 approved the
same day; spec 002 D10 and AC-API-17 amended). In the Stage 1 public demo it is protected
like the other pages (spec 014). D1 to D14 above are unchanged; D6 now reads "the menu
shows only implemented screens", which adds Prediction as a fifth menu item.

**Screen** (`/prediction`, menu item "Prediction", reference `DealDesign/prediction.png`,
read-only and never committed; the layout and hierarchy follow it, in the DealPilot dark
theme with tokens, CSS Modules and hand-drawn SVG charts, D12; no new dependency):
- Filters: level (Total, Category, Product and region), category, product, region,
  cutoff date (from dataset start + 6 to dataset end) and horizon (7, 14, 21 or 28 days).
  "Generate Forecast" calls the API. The submitted settings live in the URL (D7). The
  button is disabled while a forecast loads, so a second click sends nothing.
- KPI cards: historical units (the 28 days up to the cutoff, with the change vs the 28
  days before only when that window is fully inside the dataset and its sum is above 0),
  forecasted units (the next N days, with the change vs the last N days before the cutoff
  under the same condition), the horizon with its dates, and the served model.
- Chart: actual units up to the cutoff (solid blue), the forecast after it (dashed
  purple), a vertical cutoff marker; no confidence band and no actual value after the
  cutoff.
- Model details from the API answer and `/v1/dimensions`, with the note "Baseline
  forecast. No prediction intervals."
- Tabs: Forecast Table (Date, Day, Actual, Forecast, Difference, Abs. error, APE; an em
  dash where no actual exists, `n/a` for APE when the actual is 0) and Model Evaluation.
- No bell, avatar, user name, Settings or other control without a real function.

**Model Evaluation data.** Only genuine harness output is shown, labelled "Exploratory
backtest, not a formal evaluation": the 13-fold means (spec 003 section 7.5, open days) of
seasonal naive and naive at each level, from one exploratory backtest of the seed 42 data
(spec 003 section 9.5). It is stored as `frontend/src/evaluation/exploratory-backtest.json`,
written by `python -m dealpilot.forecasting.summary <run folder> <file>` from a run of
`python -m dealpilot.forecasting.evaluate backtest`, and checked by
`backend/tests/test_forecasting_summary.py`, which runs a fresh exploratory backtest and
requires the same numbers. No holdout result and no formal result is ever shown. Whether
this small summary file may be committed (AGENTS.md: no generated data) is pending the
product owner's decision; see the 2026-11-04 decision register entry.

**Acceptance (tests in `frontend/tests/pages/prediction.test.tsx`).** The page starts with
an empty state and no forecast request; Generate Forecast sends exactly the spec 003
section 10 parameters of the level; KPIs, chart lines, cutoff marker, details and table
equal values worked out from the fixture; loading, error, data-unavailable and cutoff
validation states; no double submit; the evaluation tab shows the harness numbers with
its label; no control without a function; public mode sends a visitor without a session
to `/welcome`.
