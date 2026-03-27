# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A collection of Slack message analysis and visualization tools (word cloud generation, message counting, unanswered mention detection, etc.). Runs on Docker containers. See README.md for the full list of scripts and arguments.

## How to Run & Test

```bash
# Docker build & run
docker build -t slackapp .
docker run --volume $PWD:/app slackapp <script>.py [args]

# Run tests
python -m pytest tests/ -v
```

## Development Rules

### Script Creation Guidelines

**IMPORTANT**: Before creating any new scripts, you MUST:

1. **Requirements Confirmation**: Clarify and confirm the exact requirements with the user
2. **Design Review**: Present a high-level design and get user approval
3. **Implementation**: Only proceed after receiving explicit approval for both requirements and design

### Code Organization

- Keep `main()` simple — orchestration only, extract complex logic into separate functions
- Each function should have a single, clear responsibility
- When using search.messages, use the shared module `slack_search.py`

## API Gotchas

### Slack API Reference

- **Web API Methods**: https://api.slack.com/methods
- **Application List**: https://api.slack.com/apps/

### Message Timestamp Format

Timestamps must include a period between the 6th and 7th digits from the right:
- `1234567890.123456` (correct)
- `1234567890123456` (wrong)

### search.messages Caveats

- **Pagination**: `search.messages` uses **page-based** pagination (`page` + `count`), unlike most other methods which use cursor-based. See: https://docs.slack.dev/apis/web-api/pagination
- **Channel ID**: The `in:` modifier requires `in:<#C07NX1JJ215>` format. Bare `in:C07NX1JJ215` does not work.
- **Keyword case**: Mixed-case keywords combined with `in:` may fail to match. `build_query()` applies `.lower()` to work around this.
- **Query Examples**:
  - `<@U123456> after:2024-01-01`
  - `<@U123456> in:<#C789012>`
  - `<@U123456> after:2024-01-01 in:<#C789012>`
- **Troubleshooting**:
  - `missing_scope` error → token needs `search:read` scope
  - Zero results → try the traditional method without `--use-search-api`

### Japanese Language Processing

- **Custom Dictionary**: Uses `dict.csv` for custom word definitions (MeCab format)
- **Stopwords**: Filters common words using `stopwords.txt`
- **Positive Word Boosting**: Emphasizes positive sentiment words with configurable multipliers
- **Compound Word Detection**: Handles adjective-noun combinations and verb conjugations
- **Text Cleaning**: Removes Slack-specific formatting, URLs, and emojis

## Slack API Rate Limits

### Rate Limit Tiers

Slack Web API methods are categorized into 4 rate limit tiers:

| Tier | Requests/minute | Required interval | Safe interval |
|------|-----------------|-------------------|---------------|
| **Tier 1** | 1+ | 60 seconds | 60 seconds |
| **Tier 2** | 20+ | 3 seconds | 3 seconds |
| **Tier 3** | 50+ | 1.2 seconds | 1.5 seconds |
| **Tier 4** | 100+ | 0.6 seconds | 1 second |

### API Methods and Their Tiers

Based on our implementation and testing, the following rate limits apply:

| API Method | Tier | Current Sleep | Notes |
|------------|------|---------------|-------|
| **reactions.list** | Special | 60s | 2025 new limit: 1 request/minute for non-Marketplace apps |
| **conversations.list** | Tier 2 | 3s | Documented example in Slack docs |
| **conversations.info** | Tier 2 | 3s | Based on observed behavior |
| **conversations.history** | Tier 3 | 1.5s | High-frequency method |
| **conversations.replies** | Tier 3 | 1.5s | Thread retrieval |
| **search.messages** | Tier 3 | 1.5s | Search API endpoint |
| **users.info** | Tier 4 | 1s | User profile lookups |

### Pagination

Most Slack Web API methods recommend cursor-based pagination, but `search.messages` is an exception — **page-based pagination is the official method**.

- **`search.messages`**: page-based (`page` + `count` params). Max `page` = 100, max `count` = 100 (= 10,000 results max)
- **`conversations.history`**, **`conversations.replies`**, etc.: cursor-based (`cursor` param)

`search.messages` does accept a `cursor` parameter, but it is not listed in the official cursor-based pagination method list.

Reference: https://docs.slack.dev/apis/web-api/pagination

### Special Rate Limits

#### reactions.list (2025 Update)
- **Old limit**: Standard tier-based limiting
- **New limit (2025/01/02)**: 1 request per minute, max 15 objects per request
- **Applies to**: Non-Marketplace apps
- **Exception**: Apps created before 2024/05/29 maintain old limits
- **Required action**: Use 60-second delays between requests

### Rate Limit Handling Best Practices

1. **Use handle_rate_limit wrapper**: Implements exponential backoff with retry logic
2. **Check for rate_limited errors**: Honor the `retry_after` value in error responses
3. **Batch operations when possible**: Reduce total API calls
4. **Use appropriate delays**: Follow the tier-based intervals above
5. **Monitor for changes**: Slack may update rate limits with notice

### Implementation Example

```python
def handle_rate_limit(func, *args, max_retries=5, base_delay=1, **kwargs):
    """Rate limit handling with exponential backoff"""
    for attempt in range(max_retries):
        try:
            return func(*args, **kwargs)
        except SlackApiError as e:
            if e.response["error"] == "rate_limited":
                retry_after = int(e.response.get("headers", {}).get("Retry-After", base_delay))
                print(f"Rate limited. Retrying after {retry_after} seconds...")
                time.sleep(retry_after)
            else:
                raise
    raise Exception(f"Failed after {max_retries} retries")
```

### Troubleshooting Rate Limits

- **internal_error**: Often indicates rate limit violation, especially with cursor-based pagination
- **rate_limited**: Explicit rate limit error with `retry_after` header
- **missing_scope**: Check token permissions, not a rate limit issue
- **invalid_cursor**: May occur after rate limiting disrupts pagination state
