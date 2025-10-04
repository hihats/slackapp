DOCKER_IMAGE = slackapp

.PHONY: unanswered-mentions-daily unanswered-mentions-weekly

# Daily version: Check unanswered mentions for the last 1 day
unanswered-mentions-daily:
	docker run --volume $(PWD):/app $(DOCKER_IMAGE) unanswered_mentions.py \
		--token $(SLACK_TOKEN) \
		--mentioned-user $(SLACK_USER_ID) \
		--days 1 \
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
