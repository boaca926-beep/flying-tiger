#!/usr/bin/env bash
# Flying Tiger pipeline: scrape → verify → test agent
set -euo pipefail
cd "$(dirname "$0")"

GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; NC='\033[0m'
step() { echo -e "\n${YELLOW}=== $* ===${NC}"; }
ok()   { echo -e "${GREEN}✓${NC} $*"; }
fail() { echo -e "${RED}✗${NC} $*"; }

DEFAULT_Q="what's on sale?"
TEST_QUESTION="${TEST_QUESTION:-$DEFAULT_Q}"

step "1/3  Scraping"
command -v uv >/dev/null 2>&1 || { fail "uv not installed"; exit 1; }
if ! uv run main.py > scrape.log 2>&1; then
    fail "scraper failed"
    tail -n 30 scrape.log | sed 's/^/    /'
    exit 1
fi
ok "scraper completed"
tail -n 8 scrape.log | sed 's/^/    /'

step "2/3  Verifying"
for f in flyingtiger.db products.csv products.json; do
    [ -s "$f" ] && ok "$f" || { fail "$f missing"; exit 1; }
done

count=$(uv run python -c "
import sqlite3
print(sqlite3.connect('flyingtiger.db').execute('SELECT COUNT(*) FROM products').fetchone()[0])
")
ok "$count products in DB"

step "3/3  Smoke-test agent"
echo "    question: $TEST_QUESTION"
if ! uv run agent.py "$TEST_QUESTION" > /tmp/ft_agent.out 2>&1; then
    fail "agent failed"
    sed 's/^/    /' /tmp/ft_agent.out
    exit 1
fi
ok "agent answered"
sed 's/^/    /' /tmp/ft_agent.out

echo
ok "Done."