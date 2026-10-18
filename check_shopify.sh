#!/usr/bin/env bash
# check_shopify.sh — Detect if websites are built on Shopify
#
# Usage:
#   ./check_shopify.sh              # check all domains in the DOMAINS array
#   ./check_shopify.sh kjell.com    # check a single domain
#
# Exit codes:
#   0 — at least one SHOPIFY match found
#   1 — no SHOPIFY matches found
#
# Detection rules (see notes at bottom):
#   [SHOPIFY] — 2+ independent Shopify signals
#   [MAYBE]   — exactly 1 signal, needs confirmation
#   [NO]      — no signals

set -euo pipefail

# ---------------------------------------------------------------------------
# Domains to check — Solna Centrum + Mall of Scandinavia retailers
# ---------------------------------------------------------------------------
DOMAINS=(
    # --- Confirmed Shopify (should show [SHOPIFY]) ---
    "flyingtiger.com"

    # --- Major Solna C retailers (test to see what platform they use) ---
    "sostrenegrene.com"
    "clasohlson.com"
    "hm.com"
    "kicks.se"
    "kjell.com"
    "urnpenn.se"
    "ginatricot.com"
    "lindex.com"
    "normal.se"
    "bikbok.com"
    "carlings.com"
    "cubus.com"
    "dressmann.com"
    "kappahl.com"
    "mq.se"
    "zara.com"
    "lyko.com"
    "sephora.se"
    "rituals.com"
    "elgiganten.se"
    "stadium.se"

    # --- Smaller Swedish Shopify stores (likely [SHOPIFY]) ---
    "nordspis.se"
    "sommarduschen.se"
)

UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
TIMEOUT=15
MAX_PARALLEL=5   # reserved for future parallel implementation; currently sequential

# ---------------------------------------------------------------------------
# Colors
# ---------------------------------------------------------------------------
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# ---------------------------------------------------------------------------
# Fetch helpers
# ---------------------------------------------------------------------------
fetch_headers() {
    curl -sI -L --max-time "$TIMEOUT" -A "$UA" "$1" 2>/dev/null || true
}

fetch_body() {
    curl -sL --max-time "$TIMEOUT" -A "$UA" "$1" 2>/dev/null || true
}

http_status() {
    curl -sL -o /dev/null -w "%{http_code}" --max-time "$TIMEOUT" -A "$UA" "$1" 2>/dev/null || echo "000"
}

# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------
check_shopify() {
    local domain="$1"
    local url="https://${domain}"
    local signals=()

    local headers body
    headers=$(fetch_headers "$url")
    body=$(fetch_body "$url")

    # Signal 1: Shopify-specific HTTP headers (STRONG)
    if echo "$headers" | grep -qiE 'X-ShopId|X-Shopify-Stage|X-Sorting-Hat-ShopId'; then
        signals+=("HTTP header (X-ShopId / X-Shopify-Stage)")
    fi

    # Signal 2: Shopify CDN assets actually loaded (MODERATE)
    if echo "$body" | grep -qiE 'src="[^"]*cdn\.shopify\.com|href="[^"]*cdn\.shopify\.com|cdn\.shopifycloud\.com'; then
        signals+=("CDN assets (cdn.shopify.com)")
    fi

    # Signal 3: window.Shopify JS object assignment (MODERATE)
    if echo "$body" | grep -qE 'window\.Shopify\s*=|Shopify\.theme\s*=|Shopify\.shop\s*='; then
        signals+=("JS object (window.Shopify)")
    fi

    # Signal 4: /products.json endpoint (STRONG — must be HTTP 200 + JSON shape)
    local json_url="${url}/products.json?limit=1"
    local json_status
    json_status=$(http_status "$json_url")

    if [ "$json_status" = "200" ]; then
        local json_body
        json_body=$(curl -sL --max-time 10 -A "$UA" "$json_url" 2>/dev/null || true)
        if echo "$json_body" | tr -d '[:space:]' | grep -qE '^\{"products"'; then
            signals+=("/products.json returns valid Shopify JSON")
        fi
    fi

    # --- Verdict ---
    local count=${#signals[@]}

    if [ "$count" -ge 2 ]; then
        printf "${GREEN}${BOLD}[SHOPIFY]${NC} %-25s\n" "$domain"
        for sig in "${signals[@]}"; do
            printf "          ${CYAN}•${NC} %s\n" "$sig"
        done
        return 0
    elif [ "$count" -eq 1 ]; then
        printf "${YELLOW}${BOLD}[MAYBE]${NC}   %-25s\n" "$domain"
        for sig in "${signals[@]}"; do
            printf "          ${CYAN}•${NC} %s\n" "$sig"
        done
        return 1
    else
        printf "${RED}${BOLD}[NO]${NC}      %-25s\n" "$domain"
        return 1
    fi
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
    local matches=0

    if [ -n "${1:-}" ]; then
        # Single-domain mode
        echo -e "${YELLOW}Checking ${1}...${NC}"
        echo "----------------------------------------"
        check_shopify "$1" && matches=1
        echo ""
        exit $(( matches == 1 ? 0 : 1 ))
    fi

    # Batch mode
    echo -e "${YELLOW}Checking ${#DOMAINS[@]} domains for Shopify...${NC}"
    echo "========================================"
    echo ""

    for domain in "${DOMAINS[@]}"; do
        check_shopify "$domain" && matches=$((matches + 1)) || true
    done

    echo "========================================"
    echo -e "${YELLOW}Summary:${NC} ${matches} Shopify match(es) out of ${#DOMAINS[@]} domains."
    echo ""

    # Non-zero exit if no matches found
    [ "$matches" -gt 0 ] && exit 0 || exit 1
}

main "$@"