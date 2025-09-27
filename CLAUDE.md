# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Python application that generates word clouds from Slack messages. It searches for messages containing specific keywords in Slack channels and creates visual word clouds from the text content using Japanese morphological analysis.

## Development Commands

### Running the Application

The application is containerized and runs through Docker:

```bash
# Build the Docker image
docker build -t slackapp .

# Run the application
docker run -v $(pwd):/app slackapp \
  --token YOUR_SLACK_TOKEN \
  --channel CHANNEL_ID \
  --keyword SEARCH_KEYWORD \
  --days 30 \
  --output outputs/filename.png
```

### Running Locally (for development)

```bash
# Install dependencies
pip install -r requirements.txt

# Run the application with Docker
docker run --volume $PWD:/app slackapp wordcloud.py --token $SLACK_TOKEN --channel $CHANNEL_ID --keyword KEYWORD
```

### Retrieving Posts with Your Reactions

```bash
# Get posts where you've added reactions
docker run --volume $PWD:/app slackapp posts_with_my_reactions.py --token $SLACK_TOKEN --days $NUMDAYS --output outputs/posts_with_my_reactions_$(date +%Y%m%d).json
```

### Retrieving Message Reactions

```bash
# Get all reactions for a specific message
docker run --volume $PWD:/app slackapp message_reactions.py --token $SLACK_TOKEN --channel $CHANNEL_ID --message $MESSAGE_TIMESTAMP --include-user-details --output outputs/reactions_to_$MESSAGE_TIMESTAMP.json
```

### Retrieving All User Channels

```bash
# Get all channels that a specific user is a member of
docker run --volume $PWD:/app slackapp get_all_channels.py --token $SLACK_TOKEN --user $SLACK_USER_ID --output outputs/all_channels.json
```

### Finding Inactive Channels

```bash
# Find channels with no activity for 365+ days (requires all_channels.json as input)
docker run --volume $PWD:/app slackapp inactive_channels.py --token $SLACK_TOKEN --channels-json outputs/inactive_channels.json --output outputs/inactive_channels_$(date +%Y%m%d).json
```

### Finding Unanswered Mentions

Find messages where a specific user was mentioned but hasn't responded:

```bash
# Traditional method (channel-by-channel search)
docker run --volume $PWD:/app slackapp unanswered_mentions.py --token $SLACK_TOKEN --mentioned-user $SLACK_USER_ID --days 30 --output outputs/unanswered_mentions_$(date +%Y%m%d).json

# High-speed method using Search API (requires search:read scope)
docker run --volume $PWD:/app slackapp unanswered_mentions.py --token $SLACK_TOKEN --mentioned-user $SLACK_USER_ID --days 30 --output outputs/unanswered_mentions_$(date +%Y%m%d).json --use-search-api

# Search in specific channel only
docker run --volume $PWD:/app slackapp unanswered_mentions.py --token $SLACK_TOKEN --mentioned-user $SLACK_USER_ID --channel $CHANNEL_ID --days 7 --output outputs/unanswered_mentions_$(date +%Y%m%d).json --use-search-api
```

### Weekly Message Count

Count messages containing specific keywords in a channel and aggregate by week:

```bash
# Count messages with specific keyword using Search API (requires search:read scope)
docker run --volume $PWD:/app slackapp weekly_message_count.py --token $SLACK_TOKEN --channel $CHANNEL_ID --keyword "検索文言" --days 30 --output outputs/weekly_count_$(date +%Y%m%d).json
```

### Available Command Line Arguments

- `--token`: Slack API token (required)
- `--channel`: Slack channel ID to search (required for wordcloud, message_reactions, weekly_message_count; optional for unanswered_mentions)
- `--user`: Slack user ID (required for get_all_channels)
- `--mentioned-user`: Slack user ID to search for mentions of (required for unanswered_mentions)
- `--channels-json`: Path to all_channels.json file (required for inactive_channels)
- `--keyword`: Search keyword (required for wordcloud, weekly_message_count)
- `--days`: Number of days to search back (default: 30)
- `--output`: Output filename (must include outputs/ directory path, e.g., outputs/filename.json)
- `--use-search-api`: Use search.messages API for faster cross-channel search (requires search:read scope)
- `--limit`: Maximum number of channels to process (optional, for testing)
- `--stopwords`: Path to stopwords file (optional)
- `--min_freq`: Minimum word frequency to include (default: 2)
- `--positive_boost`: Multiplier for positive word weights (default: 1.5)

## Architecture

### Main Components

1. **slack_wordcloud.py**: Main application entry point containing all core functionality
2. **MeCab Integration**: Uses MeCab for Japanese morphological analysis with custom dictionary support
3. **Slack API**: Uses slack-sdk for message retrieval and search
4. **Word Cloud Generation**: Uses matplotlib and wordcloud libraries for visualization

### Slack API Reference

For Slack API development, always refer to the official API documentation:
- **Web API Methods**: https://api.slack.com/methods
- **Application List**: https://api.slack.com/apps/
- Use this as the primary reference for all Slack API endpoints, parameters, and response formats

#### Message Timestamp Format
When using message timestamps as arguments in Slack API calls, ensure proper formatting:
- Message timestamps must include a period (.) between the 6th and 7th digits from the right
- Example: `1234567890.123456` (not `1234567890123456`)
- This format represents Unix timestamp with microsecond precision

#### Using the Search API (--use-search-api)

The `--use-search-api` option enables high-speed cross-channel search using Slack's `search.messages` API:

**Requirements:**
- User token (not bot token) with `search:read` scope
- Slack app with search permissions enabled

**Benefits:**
- 🚀 **Significantly faster**: Single API call vs. multiple channel-by-channel calls
- 📈 **Scales better**: Performance independent of channel count
- 🎯 **More accurate**: Uses Slack's native search engine
- 📋 **No setup required**: No need for all_channels.json file
- 🔍 **Auto-discovery**: Automatically finds all accessible channels

**Limitations:**
- 📋 **Token scope**: Requires `search:read` scope (not available for all token types)
- 🏢 **Enterprise restrictions**: Some enterprise workspaces may limit search functionality
- 🔍 **Search syntax**: Uses Slack's search query format

**Troubleshooting:**
- If you get `missing_scope` error, ensure your token has `search:read` scope
- If search returns no results, try the traditional method without `--use-search-api`
- For large workspaces, search API may have different rate limits

**Query Examples:**
- `<@U123456> after:2024-01-01`: Mentions of user after specific date
- `<@U123456> in:C789012`: Mentions in specific channel
- `<@U123456> after:2024-01-01 in:C789012`: Combined filters

### Key Functions

- `get_messages()`: Retrieves messages from Slack API with pagination support
- `tokenize_japanese()`: Performs morphological analysis using MeCab with custom rules
- `extract_words_from_tokens()`: Filters and processes tokens based on part-of-speech and custom logic
- `generate_wordcloud()`: Creates and saves word cloud images with positive word boosting

### Data Flow

1. Parse command line arguments
2. Initialize Slack API client
3. Search for messages containing keywords in specified channel
4. Process messages through MeCab morphological analyzer
5. Apply custom word filtering and positive word boosting
6. Generate word cloud visualization
7. Save output to `/app/outputs/` directory

### Japanese Language Processing

The application includes sophisticated Japanese text processing:

- **Custom Dictionary**: Uses `dict.csv` for custom word definitions (MeCab format)
- **Stopwords**: Filters common words using `stopwords.txt`
- **Positive Word Boosting**: Emphasizes positive sentiment words with configurable multipliers
- **Compound Word Detection**: Handles adjective-noun combinations and verb conjugations
- **Text Cleaning**: Removes Slack-specific formatting, URLs, and emojis

### Configuration Files

- `requirements.txt`: Python dependencies
- `Dockerfile`: Container configuration with MeCab and Japanese font setup
- `stopwords.txt`: Japanese stopwords for filtering
- `dict.csv`: Custom MeCab dictionary entries
- Output files are saved to `outputs/` directory

### Docker Environment

The application is designed to run in a Docker container with:
- Python 3.9 slim base image
- MeCab morphological analyzer with NEologd dictionary
- Japanese fonts (Noto CJK) for proper word cloud rendering
- Volume mounting for outputs directory

## Development Process

### Script Creation Guidelines

**IMPORTANT**: Before creating any new scripts, you MUST:

1. **Requirements Confirmation**: Clarify and confirm the exact requirements with the user:
   - What specific functionality is needed?
   - What are the expected inputs and outputs?
   - What are the performance requirements?
   - Are there any specific constraints or edge cases?

2. **Design Review**: Present a high-level design and get user approval:
   - Describe the main functions and their responsibilities
   - Outline the data flow and processing steps
   - Identify any dependencies on existing code or APIs
   - Propose the command-line interface and arguments
   - Suggest the output format and location

3. **Implementation**: Only proceed with code implementation after receiving explicit approval for both requirements and design.

This process ensures that the developed scripts meet the actual needs and prevents unnecessary rework.

### Code Organization Best Practices

**IMPORTANT**: Keep your code clean and maintainable by following these principles:

1. **Separation of Concerns**: 
   - Keep `main()` functions simple and focused on orchestration
   - Extract complex logic into separate, well-named functions
   - Avoid writing complex processing logic directly in `main()`

2. **Function Design**:
   - Each function should have a single, clear responsibility
   - Functions should be testable and reusable
   - Complex operations should be broken down into smaller helper functions

3. **Example of Good Practice**:
   ```python
   # Good: main() is simple and delegates to specific functions
   def main():
       args = parse_arguments()
       client = initialize_client(args.token)
       messages = fetch_messages(client, args)
       processed_data = process_messages(messages)
       save_results(processed_data, args.output)
   
   # Bad: main() contains complex processing logic
   def main():
       args = parse_arguments()
       client = WebClient(token=args.token)
       # Avoid: 100+ lines of complex processing logic here
   ```

4. **Refactoring Guidelines**:
   - When modifying existing code, consider refactoring if `main()` becomes too complex
   - Extract repeated code into utility functions
   - Group related functionality into logical modules

## Usage Examples

### Complete Workflow: Finding Unanswered Mentions

#### Option A: Using Search API (Recommended)

**No preparation needed!** Search API finds all accessible channels automatically:

```bash
# Direct execution - no all_channels.json required
docker run --volume $PWD:/app slackapp unanswered_mentions.py --token $SLACK_TOKEN --mentioned-user $SLACK_USER_ID --days 30 --output outputs/unanswered_mentions_$(date +%Y%m%d).json --use-search-api
```

#### Option B: Traditional Method (Requires Setup)

1. **First, get all channels**:
```bash
docker run --volume $PWD:/app slackapp get_all_channels.py --token $SLACK_TOKEN --user $SLACK_USER_ID --output outputs/all_channels.json
```

2. **Then find unanswered mentions**:
```bash
docker run --volume $PWD:/app slackapp unanswered_mentions.py --token $SLACK_TOKEN --mentioned-user $SLACK_USER_ID --days 30 --output outputs/unanswered_mentions_$(date +%Y%m%d).json
```

### Performance Comparison

**Search API method (`--use-search-api`):**
- ⚡ Single search query across all channels
- 🚀 Typical execution: 1-3 minutes for large workspaces
- 📊 Handles 100+ channels efficiently

**Traditional method (without flag):**
- 🔄 Channel-by-channel search
- ⏰ Typical execution: 10-60 minutes for large workspaces
- 📈 Time scales linearly with channel count

**Recommendation:** Always try `--use-search-api` first. Fall back to traditional method only if you encounter scope or permission issues.