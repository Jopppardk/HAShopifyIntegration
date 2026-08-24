# Shopify Performance

A Home Assistant custom integration exposing Shopify revenue and inventory performance.

- Revenue today
- Revenue year to date
- Revenue previous month
- Revenue current month
- Revenue last year at this time
- Inventory value at cost
- Revenue LTM (latest 12 months, including the current partial month)
- Comparable LTM revenue for the same months one year earlier
- LTM year-over-year change
- A 12-row monthly comparison dataset for dashboard charts

## Requirements

- Home Assistant 2025.1 or newer
- A Shopify app created in the Dev Dashboard, owned by the same Shopify organization as the store
- The app installed on the target store
- The `read_orders` scope
- The `read_all_orders` scope when year-to-date data can be older than Shopify's default 60-day order window
- The `read_inventory` or `read_products` scope, plus permission to view product costs, for inventory value

Shopify's client credentials grant only works for apps developed by your own organization and stores owned by that organization.

## Installation

Add this repository to HACS as a custom repository of type **Integration**, install **Shopify Performance**, and restart Home Assistant. Alternatively, copy `custom_components/shopify_performance` into Home Assistant's `custom_components` directory.

Go to **Settings → Devices & services → Add integration**, search for **Shopify Performance**, and enter:

- Store domain, such as `mystore.myshopify.com` (`mystore.myshopify` is also accepted)
- Client ID
- Client secret

Credentials are stored in the Home Assistant config entry. They are never included in source files or logs. Access tokens are held only in memory.

## Revenue definition

Both sensors use `currentTotalPriceSet.shopMoney.amount` from Shopify orders. This is the order's current total in the shop currency, including changes from returns, refunds, and order edits/removals.

The integration selects orders by `createdAt`, excludes orders whose `cancelledAt` is set, includes all other order/payment states, and sums values using decimal arithmetic. The same field and rules are used for both sensors.

This is gross current order value—not an accounting payout, cash-flow, tax, or profit metric. A fully refunded, non-cancelled order normally contributes its remaining current total (typically zero).

The year starts January 1, today starts at midnight, current month starts on day 1, and previous month covers the complete preceding calendar month in Home Assistant's configured timezone. “Revenue last year at this time” covers January 1 last year through the equivalent local date and time last year. Boundaries are converted to UTC only for Shopify queries.

Inventory value is a point-in-time estimate: for every tracked inventory item with a unit cost, the integration sums positive `available` quantities across all active Shopify locations and multiplies that quantity by `unitCost`. Untracked items, items without unit cost, and zero or negative available quantities contribute zero.

## Rolling monthly comparison

The integration keeps a rolling window of the latest 12 calendar months and aligns each month with the same calendar month one year earlier. Eleven completed months are compared as full months. The current partial month is compared only through the equivalent local date and time in the previous year.

For example, on August 24, 2026, the window is September 2025 through August 2026 and is aligned with September 2024 through August 24, 2025. At the start of September, the window moves forward automatically.

The 24-month history query is refreshed every six hours to limit Shopify API load. Live operational sensors continue to refresh every five minutes. The `sensor.shopify_monthly_revenue` entity exposes the aligned rows in its `months` attribute for dashboard use.

## Updates and authentication

Data is polled every five minutes. The integration obtains an Admin API token with the OAuth client credentials grant. It caches the token in memory, requests a replacement shortly before expiry, and retries once with a new token if Shopify returns HTTP 401.

The integration is read-only and performs GraphQL queries only.

## Entities

- `sensor.shopify_revenue_today`
- `sensor.shopify_revenue_year_to_date`
- `sensor.shopify_revenue_previous_month`
- `sensor.shopify_revenue_current_month`
- `sensor.shopify_revenue_last_year_same_time`
- `sensor.shopify_inventory_value`
- `sensor.shopify_revenue_ltm`
- `sensor.shopify_revenue_ltm_previous_year`
- `sensor.shopify_revenue_ltm_change_percent`
- `sensor.shopify_monthly_revenue`

Entity IDs can vary if Home Assistant resolves a naming collision.

## Dashboard example

An ApexCharts dashboard example is available at [`examples/shopify_performance_dashboard.yaml`](examples/shopify_performance_dashboard.yaml). Install ApexCharts Card through HACS before using the chart.

## API version

v0.2.1 targets Shopify Admin GraphQL API `2026-07`.

## License

MIT

