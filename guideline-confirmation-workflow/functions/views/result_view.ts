import { Quiz } from "../../data/quiz_loader.ts";

export function buildCorrectResultView(quiz: Quiz) {
  return {
    response_action: "update" as const,
    view: {
      type: "modal" as const,
      callback_id: "result_view",
      title: { type: "plain_text" as const, text: "理解度テスト結果" },
      close: { type: "plain_text" as const, text: "閉じる" },
      blocks: [
        {
          type: "section",
          text: {
            type: "mrkdwn",
            text: ":white_check_mark: *全問正解！*",
          },
        },
        { type: "divider" },
        {
          type: "context",
          elements: [
            {
              type: "mrkdwn",
              text: `*${quiz.category}*: ${quiz.question}`,
            },
          ],
        },
        {
          type: "section",
          text: { type: "mrkdwn", text: quiz.explanation },
        },
      ],
    },
  };
}
