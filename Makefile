DOCKER_IMAGE = slackapp

# Default values
DAYS ?= 1

.PHONY: unanswered-mentions-daily unanswered-mentions-weekly posts-with-reactions-weekly posts-with-reactions-quarterly posts-with-reactions-monthly

# Daily version: Check unanswered mentions for the last 1 day
unanswered-mentions-daily:
	docker run --volume $(PWD):/app $(DOCKER_IMAGE) unanswered_mentions.py \
		--token $(SLACK_TOKEN) \
		--mentioned-user $(SLACK_USER_ID) \
		--days $(DAYS) \
		--output outputs/daily_unanswered_mentions_$(shell date +%Y%m%d).json \
		--use-search-api

# Weekly version: Check unanswered mentions for the last 7 days
unanswered-mentions-weekly:
	docker run --volume $(PWD):/app $(DOCKER_IMAGE) unanswered_mentions.py \
		--token $(SLACK_TOKEN) \
		--mentioned-user $(SLACK_USER_ID) \
		--days 7 \
		--output outputs/weekly_unanswered_mentions_$(shell date +%Y%m%d).json \
		--use-search-api

# Weekly version: Get posts with my reactions for the last 7 days
posts-with-reactions-weekly:
	docker run --volume $(PWD):/app $(DOCKER_IMAGE) posts_with_my_reactions.py \
		--token $(SLACK_TOKEN) \
		--days 7 \
		--output outputs/weekly_posts_with_my_reactions_$(shell date +%Y%m%d).json

# Monthly version: Get posts with my reactions for the last 31 days
posts-with-reactions-quarterly:
	docker run --volume $(PWD):/app $(DOCKER_IMAGE) posts_with_my_reactions.py \
		--token $(SLACK_TOKEN) \
		--days 180 \
		--output outputs/auarterly_posts_with_my_reactions_$(shell date +%Y%m%d).json
# Monthly version: Get posts with my reactions for the last 31 days
posts-with-reactions-monthly:
	docker run --volume $(PWD):/app $(DOCKER_IMAGE) posts_with_my_reactions.py \
		--token $(SLACK_TOKEN) \
		--days 31 \
		--output outputs/monthly_posts_with_my_reactions_$(shell date +%Y%m%d).json
