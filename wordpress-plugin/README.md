# WordPress Plugin

## Purpose
Sync external links from WordPress posts into the Affiliate Link Integrity Checker.

## Setup
1. Copy `affiliate-link-integrity-checker.php` into `wp-content/plugins/affiliate-link-integrity-checker/`
2. Activate the plugin in WordPress
3. Open `Settings -> Affiliate Link Checker`
4. Set:
   - API Base URL
   - API Key
   - Project ID
   - Merchant Name

## Behavior
- Auto-sync runs on post save when enabled
- Only external HTTP/HTTPS links are sent
- Sync uses `X-API-Key` and the WordPress integration endpoint
