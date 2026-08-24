"""Constants for Shopify Performance."""

from datetime import timedelta

DOMAIN = "shopify_performance"
PLATFORMS = ["sensor"]

CONF_SHOP_DOMAIN = "shop_domain"

API_VERSION = "2026-07"
UPDATE_INTERVAL = timedelta(minutes=5)
MONTHLY_UPDATE_INTERVAL = timedelta(hours=6)

DATA_COORDINATOR = "coordinator"

