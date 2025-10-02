#!/bin/bash

# CLAUDE.md line count checker
# Shared script for pre-commit hook and GitHub Actions

# Configuration
MAX_LINES=500
CLAUDE_FILE="CLAUDE.md"

# Colors for terminal output (disabled in CI)
if [ -t 1 ] && [ -z "$CI" ]; then
    RED='\033[0;31m'
    YELLOW='\033[0;33m'
    GREEN='\033[0;32m'
    BLUE='\033[0;34m'
    NC='\033[0m' # No Color
else
    RED=''
    YELLOW=''
    GREEN=''
    BLUE=''
    NC=''
fi

# Function to analyze sections
analyze_sections() {
    local file=$1
    grep -n "^## " "$file" | while IFS=: read -r num heading; do
        next_num=$(grep -n "^## " "$file" | grep -A1 "^$num:" | tail -1 | cut -d: -f1)
        if [ -z "$next_num" ]; then
            next_num=$(wc -l < "$file")
            next_num=$((next_num + 1))
        fi
        lines=$((next_num - num))
        printf "   %-50s %4d lines\n" "$heading" "$lines"
    done | sort -t$'\t' -k2 -rn | head -5
}

# Function to check CLAUDE.md
check_claude_md() {
    local interactive=${1:-true}  # Default to interactive mode

    if [ ! -f "$CLAUDE_FILE" ]; then
        echo "ℹ️  $CLAUDE_FILE not found"
        return 0
    fi

    local CLAUDE_LINES=$(wc -l < "$CLAUDE_FILE")
    local USAGE=$((CLAUDE_LINES * 100 / MAX_LINES))

    # GitHub Actions output
    if [ "$CI" = "true" ]; then
        echo "lines=$CLAUDE_LINES" >> "$GITHUB_OUTPUT"
        echo "usage=$USAGE" >> "$GITHUB_OUTPUT"
    fi

    if [ "$CLAUDE_LINES" -gt "$MAX_LINES" ]; then
        echo ""
        echo -e "${YELLOW}⚠️  警告: $CLAUDE_FILE が $CLAUDE_LINES 行になりました（推奨: ${MAX_LINES}行以下）${NC}"
        echo ""
        echo -e "${BLUE}📝 ドキュメントの分割を検討してください:${NC}"
        echo "   - API_GUIDELINES.md: API関連の詳細情報"
        echo "   - DEVELOPMENT_GUIDE.md: 開発プロセスのガイドライン"
        echo "   - 使用頻度の低いセクションの外部化"
        echo ""
        echo -e "${BLUE}📊 主要セクションの行数:${NC}"
        analyze_sections "$CLAUDE_FILE"
        echo ""
        echo -e "${BLUE}📈 使用状況:${NC}"
        echo "   現在: $CLAUDE_LINES 行"
        echo "   上限: $MAX_LINES 行"
        echo "   使用率: ${USAGE}%"
        echo ""

        # GitHub Actions warning
        if [ "$CI" = "true" ]; then
            echo "::warning file=$CLAUDE_FILE,title=Documentation Size::$CLAUDE_FILE has $CLAUDE_LINES lines (recommended: ≤$MAX_LINES)"
            echo "status=warning" >> "$GITHUB_OUTPUT"
        fi

        # Interactive mode (for pre-commit)
        if [ "$interactive" = "true" ] && [ -z "$CI" ]; then
            read -p "このままコミットを続行しますか？ (y/n) " -n 1 -r
            echo
            if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                echo -e "${RED}❌ コミットをキャンセルしました${NC}"
                echo "💡 ヒント: 'git commit --no-verify' でこのチェックをスキップできます"
                return 1
            fi
        fi

        return 2  # Return 2 for warning
    else
        echo -e "${GREEN}✅ $CLAUDE_FILE: $CLAUDE_LINES 行 (${USAGE}%)${NC}"

        # GitHub Actions notice
        if [ "$CI" = "true" ]; then
            echo "::notice file=$CLAUDE_FILE,title=Documentation Size::$CLAUDE_FILE has $CLAUDE_LINES lines (OK)"
            echo "status=ok" >> "$GITHUB_OUTPUT"
        fi

        return 0
    fi
}

# Main execution
if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
    # Check if running in CI or interactive mode
    if [ "$1" = "--non-interactive" ] || [ "$CI" = "true" ]; then
        check_claude_md false
    else
        check_claude_md true
    fi
    exit $?
fi