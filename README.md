# Shopify Integration

A Home Assistant custom integration exposing Shopify revenue and inventory performance.

- Revenue today
- Revenue year to date
- Revenue previous month
- Revenue current month
- Revenue current month in the previous year, through the equivalent date and time
- Full revenue for the same calendar month in the previous year
- Month-to-date year-over-year change
- Forecast revenue for the current month and forecast change
- Revenue last year at this time
- Inventory value at cost
- Revenue LTM (latest 12 months, including the current partial month)
- Comparable LTM revenue for the same months one year earlier
- LTM year-over-year change
- A 12-row monthly comparison dataset for dashboard charts
- Sessions today, month to date, and year to date
- Orders today, month to date, and year to date
- Online store conversion rate today, month to date, and year to date
- Sessions with cart additions today, month to date, and year to date
- Sessions that reached checkout today, month to date, and year to date
- Sessions that completed checkout today, month to date, and year to date

## Requirements

- Home Assistant 2025.1 or newer
- A Shopify app created in the Dev Dashboard, owned by the same Shopify organization as the store
- The app installed on the target store
- The `read_orders` scope
- The `read_all_orders` scope when year-to-date data can be older than Shopify's default 60-day order window
- The `read_inventory` or `read_products` scope, plus permission to view product costs, for inventory value
- The `write_inventory` scope and permission to update inventory for the optional stocktake dashboard
- The `read_reports` scope and Shopify Level 2 protected customer data access for ShopifyQL analytics

Shopify's client credentials grant only works for apps developed by your own organization and stores owned by that organization.

## Installation

Add this repository to HACS as a custom repository of type **Integration**, install **Shopify Integration**, and restart Home Assistant. Alternatively, copy `custom_components/shopify_integration` into Home Assistant's `custom_components` directory.

Go to **Settings → Devices & services → Add integration**, search for **Shopify Integration**, and enter:

- Store domain, such as `mystore.myshopify.com` (`mystore.myshopify` is also accepted)
- Client ID
- Client secret

Credentials are stored in the Home Assistant config entry. They are never included in source files or logs. Access tokens are held only in memory.

## Revenue definition

Both sensors use `currentTotalPriceSet.shopMoney.amount` from Shopify orders. This is the order's current total in the shop currency, including changes from returns, refunds, and order edits/removals.

The integration selects orders by `createdAt`, excludes orders whose `cancelledAt` is set, includes all other order/payment states, and sums values using decimal arithmetic. The same field and rules are used for both sensors.

This is gross current order value—not an accounting payout, cash-flow, tax, or profit metric. A fully refunded, non-cancelled order normally contributes its remaining current total (typically zero).

The year starts January 1, today starts at midnight, current month starts on day 1, and previous month covers the complete preceding calendar month in Home Assistant's configured timezone. “Revenue current month previous year” covers the same calendar month last year from its first day through the equivalent local date and time. “Revenue last year at this time” covers January 1 last year through the equivalent local date and time last year. Boundaries are converted to UTC only for Shopify queries.

Inventory value uses the same basis as the stocktake dashboard: active products with tracked variants at the store's single active location. For each variant, physical `on_hand` quantity is multiplied by Shopify `unitCost`. Variants without unit cost are excluded. This keeps `sensor.shopify_integration_inventory_value` equal to the stocktake card's original inventory value.

## Current month forecast

The month-to-date pace compares current-month revenue with revenue through the equivalent local date and time in the same calendar month last year:

`MTD change = (current MTD / previous-year MTD - 1) × 100`

The forecast applies that pace to the complete comparable month last year:

`forecast = full comparable month last year × current MTD / previous-year MTD`

This preserves the store's actual within-month sales pattern from the previous year instead of assuming that every day contributes equally. When previous-year MTD is zero, the forecast and percentage sensors are unavailable rather than presenting a misleading estimate. Forecast values are estimates and can move up or down as orders, refunds, returns, and edits change the underlying current order totals.

## Rolling monthly comparison

The integration keeps a rolling window of the latest 12 calendar months and aligns each month with the same calendar month one year earlier. Eleven completed months are compared as full months. The current partial month is compared only through the equivalent local date and time in the previous year.

For example, on August 24, 2026, the window is September 2025 through August 2026 and is aligned with September 2024 through August 24, 2025. At the start of September, the window moves forward automatically.

The 24-month history query is refreshed every six hours to limit Shopify API load. Live operational sensors continue to refresh every five minutes. The `sensor.shopify_integration_monthly_revenue` entity exposes the aligned rows in its `months` attribute for dashboard use.

## Inventory counting dashboard

Version 0.9.0 adds an administrator-only bulk stocktake card for stores with exactly one active Shopify location. It lists every active inventory-tracked variant, shows Shopify's physical `on_hand` quantity, accepts counted quantities inline, and sends only changed rows when **Gennemgå og opdater lager** is confirmed.

Updates use Shopify's `inventorySetOnHandQuantities` mutation with an idempotency key and `changeFromQuantity` compare-and-set protection. If an order or another process changes a quantity after the list was loaded, that row is returned for review instead of being overwritten. The feature updates Shopify inventory only; it does not post accounting entries or communicate with Dinero.

Add this JavaScript module under **Settings → Dashboards → Resources**:

```text
/shopify_integration/shopify-inventory-card.js?v=0.10.0
```

Select **JavaScript module** as the resource type. Then add the card:

```yaml
type: custom:shopify-inventory-card
title: Lageroptælling
grid_options:
  columns: full
```

Only Home Assistant administrators can load or update the inventory through this card. An example full dashboard is available at [`examples/shopify_inventory_dashboard.yaml`](examples/shopify_inventory_dashboard.yaml).


## Packaging dashboard

Version 0.11.0 adds an administrator-only packaging overview based on successful Shopify fulfillments. Reporting periods use Home Assistant's configured timezone and show both the current calendar quarter and year to date. Each sold unit contributes the packaging weight saved on its Shopify product.

Create these product metafields in Shopify:

| Metafield | Recommended type | Meaning |
| --- | --- | --- |
| `custom.emballage_indberetning` | Single-line text or dropdown | `Ja`, `Nej`, or `Uafklaret` |
| `custom.emballage_vaegt_gram` | Integer | Packaging grams per sold unit |
| `custom.emballage_leverandor` | Single-line text | Packaging supplier |
| `custom.emballage_leverandorland` | Single-line text | Supplier country |
| `custom.emballage_leverandor_cvr` | Single-line text | Supplier CVR/VAT number |

The integration snapshots the product metadata for each fulfillment line the first time it is observed. Complete snapshots remain fixed, so later product edits do not rewrite valid historical packaging records. Snapshots with an `Uafklaret` reporting status or missing packaging weight are refreshed automatically from Shopify until completed. Cancelled or removed fulfillments are excluded when Shopify no longer returns them as active successful fulfillments.

The dashboard also stores manual packaging records in Home Assistant's private `.storage` area. A manual record contains date, description, supplier, supplier country, supplier CVR/VAT number, total weight, and reporting status.

The card estimates variable packaging cost from reportable weight. The default 2026 rate is DKK 3.79/kg, matching Emballage Indberetning's standard under-8-ton household-packaging rate at release time. Administrators can edit the rate directly on the card; it is stored privately in Home Assistant. Estimates exclude VAT, membership fees, authority fees, and other fixed charges.

Add this JavaScript module under **Settings → Dashboards → Resources**:

```text
/shopify_integration/shopify-packaging-card.js?v=0.12.0
```

Select **JavaScript module**, then add:

```yaml
type: custom:shopify-packaging-card
title: Emballageoverblik
grid_options:
  columns: full
```

Only Home Assistant administrators can view or edit this card. The Shopify app needs `read_orders` and `read_products`; YTD history beyond Shopify's normal 60-day order window also needs `read_all_orders`. An example is available at [`examples/shopify_packaging_dashboard.yaml`](examples/shopify_packaging_dashboard.yaml).

### Packaging limitations in v0.11.0

- Reportability follows the product/manual `Ja/Nej/Uafklaret` value. The integration does not inspect a customer's delivery country and therefore does not automatically exclude exports.
- Household versus commercial packaging is not classified yet. Add that dimension before relying on the dashboard for a filing that requires this split.
- There is no CSV export yet. Keep invoices, weight documentation, and the submitted report outside Home Assistant as the authoritative compliance record.

## Updates and authentication

Data is polled every five minutes. The integration obtains an Admin API token with the OAuth client credentials grant. It caches the token in memory, requests a replacement shortly before expiry, and retries once with a new token if Shopify returns HTTP 401.

Shopify data collection is read-only. The optional stocktake card can write inventory only after an administrator confirms the changes; packaging manual entries are stored locally in Home Assistant.

## Sessions, orders, and conversion

Traffic metrics use ShopifyQL Analytics and refresh every five minutes. Sessions include human online-store sessions only; bot sessions are excluded. Conversion rate is calculated as sessions that completed checkout divided by sessions, multiplied by 100, and is shown with one decimal place. Order counts use Shopify Analytics' `orders` metric filtered to the `Online Store` sales channel. These reporting periods follow Shopify Analytics' reporting calendar and store timezone. Cart counts use `sessions_with_cart_additions`, and checkout counts use `sessions_that_reached_checkout`; these are session-based funnel metrics rather than counts of unique customers.

## Entities

- `sensor.shopify_integration_revenue_today`
- `sensor.shopify_integration_revenue_year_to_date`
- `sensor.shopify_integration_revenue_previous_month`
- `sensor.shopify_integration_revenue_current_month`
- `sensor.shopify_integration_revenue_current_month_previous_year`
- `sensor.shopify_integration_revenue_current_month_previous_year_full`
- `sensor.shopify_integration_revenue_month_to_date_change_percent`
- `sensor.shopify_integration_revenue_current_month_forecast`
- `sensor.shopify_integration_revenue_current_month_forecast_change_percent`
- `sensor.shopify_integration_revenue_last_year_same_time`
- `sensor.shopify_integration_inventory_value`
- `sensor.shopify_integration_revenue_ltm`
- `sensor.shopify_integration_revenue_ltm_previous_year`
- `sensor.shopify_integration_revenue_ltm_change_percent`
- `sensor.shopify_integration_monthly_revenue`
- `sensor.shopify_integration_sessions_today`
- `sensor.shopify_integration_sessions_month_to_date`
- `sensor.shopify_integration_sessions_year_to_date`
- `sensor.shopify_integration_orders_today`
- `sensor.shopify_integration_orders_month_to_date`
- `sensor.shopify_integration_orders_year_to_date`
- `sensor.shopify_integration_conversion_rate_today`
- `sensor.shopify_integration_conversion_rate_month_to_date`
- `sensor.shopify_integration_conversion_rate_year_to_date`
- `sensor.shopify_integration_carts_created_today`
- `sensor.shopify_integration_carts_created_month_to_date`
- `sensor.shopify_integration_carts_created_year_to_date`
- `sensor.shopify_integration_checkouts_reached_today`
- `sensor.shopify_integration_checkouts_reached_month_to_date`
- `sensor.shopify_integration_checkouts_reached_year_to_date`
- `sensor.shopify_integration_checkouts_completed_today`
- `sensor.shopify_integration_checkouts_completed_month_to_date`
- `sensor.shopify_integration_checkouts_completed_year_to_date`

Entity IDs can vary if Home Assistant resolves a naming collision.

## Dashboard example

An ApexCharts dashboard example is available at [`examples/shopify_integration_dashboard.yaml`](examples/shopify_integration_dashboard.yaml). Install ApexCharts Card through HACS before using the chart.

## API version

v0.9.0 targets Shopify Admin GraphQL API `2026-07`.

## License

MIT



### Inventory value during stocktake

The stocktake table shows Shopify unit costs, row values, resizable columns, and live original/corrected inventory value totals. Variants without unit cost are excluded and identified.
