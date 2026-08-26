#!/bin/bash

set -euo pipefail

# Resolve the directory containing this script.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# The project root is the parent directory of scripts/.
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "Project root: $PROJECT_ROOT"
echo "Clearing Python cache..."

# Always operate from the project root.
cd "$PROJECT_ROOT"

echo "Clearing .pyc files..."
find . -type f -name "*.pyc" -delete

echo "Clearing __pycache__ directories..."
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null

# Verify that all cache files and directories were removed.
pyc_count=$(find . -type f -name "*.pyc" | wc -l | tr -d ' ')
pycache_count=$(find . -type d -name "__pycache__" | wc -l | tr -d ' ')

if [ "$pyc_count" -eq 0 ] && [ "$pycache_count" -eq 0 ]; then
    echo "Done. Cache cleared."
else
    echo "Warning: $pyc_count .pyc file(s) and $pycache_count __pycache__ dir(s) remain."
    exit 1
fi
