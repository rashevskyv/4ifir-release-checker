# 4ifir Release Bot

An automated Telegram bot for managing GitHub releases from Telegram messages. The bot monitors a specific Telegram group or topic, processes zip files posted there, and automatically creates new GitHub releases.

## Features

- Automatically creates GitHub releases from files sent to a specified Telegram group/topic
- Handles both single messages and media groups with multiple files
- Preserves important files across releases by fetching them from previous releases if not included in the current message
- Runs verification scripts after successful release creation
- Displays download statistics badge for each release
- Comprehensive logging to a dedicated Telegram chat

## Setup

1. Clone this repository
2. Install requirements: `pip install -r requirements.txt`
3. Create a `config.json` file in the root directory (see format below)
4. Run the bot: `python main.py`

## Configuration

Create a `config.json` file with the following structure:

```json
{
  "telegram": {
    "api_id": "YOUR_TELEGRAM_API_ID",
    "api_hash": "YOUR_TELEGRAM_API_HASH",
    "group_id": -1001234567890,
    "topic_id": 123456,
    "log_chat_id": -1001234567891
  },
  "github": {
    "token": "YOUR_GITHUB_TOKEN",
    "owner": "GITHUB_USERNAME_OR_ORG",
    "repo": "REPOSITORY_NAME"
  },
  "release": {
    "file_pattern": "*.zip"
  }
}
```

- `telegram.api_id` and `telegram.api_hash`: Obtain from [my.telegram.org](https://my.telegram.org)
- `telegram.group_id`: ID of the Telegram group to monitor
- `telegram.topic_id`: ID of the specific topic within the group (if applicable)
- `telegram.log_chat_id`: ID of the chat where logs will be sent
- `github.token`: Your GitHub personal access token with repo permissions
- `github.owner`: Your GitHub username or organization name
- `github.repo`: The repository name for releases
- `release.file_pattern`: Pattern for files to include in releases

## How It Works

1. Send zip files to the configured Telegram group/topic
2. The bot will automatically process them and create a new GitHub release
3. Required files missing from the message will be fetched from previous releases
4. The bot will report success or failure to the configured log chat

## Required Files

The bot ensures these files are always included in each release:
- AIO.zip
- 4IFIX.zip

If they're not included in the new message, the bot will fetch them from previous releases.