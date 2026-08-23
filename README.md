# Shopify Performance

A minimal Home Assistant custom integration exposing Shopify revenue as three sensors:

- Revenue today
- Revenue year to date
- Revenue previous month

## Requirements

- Home Assistant 2025.1 or newer
- A Shopify app created in the Dev Dashboard, owned by the same Shopify organization as the store
- The app installed on the target store
- The `read_orders` scope
- The `read_all_orders` scope when year-to-date data can be older than Shopify's default 60-day order window

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

The year starts January 1, today starts at midnight, and previous month covers the complete preceding calendar month in Home Assistant's configured timezone. Boundaries are converted to UTC only for Shopify queries.

## Updates and authentication

Data is polled every five minutes. The integration obtains an Admin API token with the OAuth client credentials grant. It caches the token in memory, requests a replacement shortly before expiry, and retries once with a new token if Shopify returns HTTP 401.

The integration is read-only and performs GraphQL queries only.

## Entities

- `sensor.shopify_revenue_today`
- `sensor.shopify_revenue_year_to_date`
- `sensor.shopify_revenue_previous_month`

Entity IDs can vary if Home Assistant resolves a naming collision.

## API version

v0.1.1 targets Shopify Admin GraphQL API `2026-07`.

## License

MIT

