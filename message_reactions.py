#!/usr/bin/env python3
"""
Slack Message Reactions Retrieval Script

This script retrieves reaction data for a specific Slack message and outputs it in JSON format.
"""

import argparse
import json
import sys
from datetime import datetime
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError


def get_message_reactions(client, channel, message_ts, include_user_details=False):
    """
    Get reactions for a specific message.
    
    Args:
        client: Slack WebClient instance
        channel: Channel ID
        message_ts: Message timestamp
        include_user_details: Whether to include detailed user information
    
    Returns:
        dict: Reaction data including message info and reactions
    """
    try:
        # Get message reactions
        response = client.reactions_get(
            channel=channel,
            timestamp=message_ts,
            full=True
        )
        
        if not response["ok"]:
            raise Exception(f"API error: {response.get('error', 'Unknown error')}")
        
        message_data = response["message"]
        
        # Initialize result structure
        result = {
            "message_id": message_ts,
            "channel": channel,
            "message_text": message_data.get("text", ""),
            "message_user": message_data.get("user", ""),
            "message_ts": message_ts,
            "reactions": []
        }
        
        # Process reactions if they exist
        if "reactions" in message_data:
            for reaction in message_data["reactions"]:
                reaction_data = {
                    "name": reaction["name"],
                    "count": reaction["count"],
                    "users": []
                }
                
                # Process users who reacted
                for user_id in reaction["users"]:
                    user_data = {"id": user_id}
                    
                    if include_user_details:
                        try:
                            user_info = client.users_info(user=user_id)
                            if user_info["ok"]:
                                user_profile = user_info["user"]
                                user_data.update({
                                    "name": user_profile.get("name", ""),
                                    "display_name": user_profile.get("profile", {}).get("display_name", ""),
                                    "real_name": user_profile.get("profile", {}).get("real_name", "")
                                })
                        except SlackApiError as e:
                            print(f"Warning: Could not get user info for {user_id}: {e}", file=sys.stderr)
                    
                    reaction_data["users"].append(user_data)
                
                result["reactions"].append(reaction_data)
        
        return result
        
    except SlackApiError as e:
        error_msg = f"Slack API error: {e.response['error']}"
        if e.response['error'] == 'message_not_found':
            error_msg += f" - Message {message_ts} not found in channel {channel}"
        elif e.response['error'] == 'channel_not_found':
            error_msg += f" - Channel {channel} not found"
        elif e.response['error'] == 'not_in_channel':
            error_msg += f" - Bot is not in channel {channel}"
        raise Exception(error_msg)


def main():
    parser = argparse.ArgumentParser(
        description="Retrieve reaction data for a specific Slack message",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python slack_message_reactions.py --token xoxb-xxx --channel C1234567890 --message 1234567890.123456
  python slack_message_reactions.py --token xoxb-xxx --channel C1234567890 --message 1234567890.123456 --include-user-details --output my_reactions.json
        """
    )
    
    parser.add_argument("--token", required=True, help="Slack API token")
    parser.add_argument("--channel", required=True, help="Channel ID")
    parser.add_argument("--message", required=True, help="Message timestamp")
    parser.add_argument("--output", default="reactions.json", help="Output JSON file (default: reactions.json)")
    parser.add_argument("--include-user-details", action="store_true", 
                       help="Include detailed user information (name, display_name, real_name)")
    
    args = parser.parse_args()
    
    # Initialize Slack client
    client = WebClient(token=args.token)
    
    try:
        # Test authentication
        auth_response = client.auth_test()
        if not auth_response["ok"]:
            print(f"Authentication failed: {auth_response.get('error', 'Unknown error')}", file=sys.stderr)
            sys.exit(1)
        
        print(f"Authenticated as: {auth_response['user']}")
        
        # Get message reactions
        print(f"Retrieving reactions for message {args.message} in channel {args.channel}...")
        reaction_data = get_message_reactions(
            client, 
            args.channel, 
            args.message, 
            args.include_user_details
        )
        
        # Save to JSON file
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(reaction_data, f, ensure_ascii=False, indent=2)
        
        print(f"Reaction data saved to {args.output}")
        
        # Print summary
        total_reactions = sum(r["count"] for r in reaction_data["reactions"])
        unique_reactions = len(reaction_data["reactions"])
        
        print(f"Summary:")
        print(f"  - Total reactions: {total_reactions}")
        print(f"  - Unique reaction types: {unique_reactions}")
        
        if reaction_data["reactions"]:
            print(f"  - Reaction types: {', '.join([r['name'] for r in reaction_data['reactions']])}")
        
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()