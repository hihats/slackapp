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

### Available Command Line Arguments

- `--token`: Slack API token (required)
- `--channel`: Slack channel ID to search (required for wordcloud, message_reactions)
- `--user`: Slack user ID (required for get_all_channels)
- `--channels-json`: Path to all_channels.json file (required for inactive_channels)
- `--keyword`: Search keyword (required for wordcloud)
- `--days`: Number of days to search back (default: 30)
- `--output`: Output filename (must include outputs/ directory path, e.g., outputs/filename.json)
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