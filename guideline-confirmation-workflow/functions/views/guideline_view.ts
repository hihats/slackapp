import guideline from "../../data/guideline.json" with { type: "json" };

export function buildGuidelineView(interactivityPointer: string) {
  const summaryText = guideline.summary
    .map((item: string, i: number) => `${i + 1}. ${item}`)
    .join("\n");

  return {
    interactivity_pointer: interactivityPointer,
    view: {
      type: "modal" as const,
      callback_id: "guideline_view",
      title: { type: "plain_text" as const, text: "ガイドライン確認" },
      submit: { type: "plain_text" as const, text: "理解しました" },
      close: { type: "plain_text" as const, text: "閉じる" },
      blocks: [
        {
          type: "header",
          text: { type: "plain_text", text: guideline.title },
        },
        {
          type: "section",
          text: {
            type: "mrkdwn",
            text: `\nガイドラインURL: ${guideline.url}`,
          },
        },
        { type: "divider" },
        {
          type: "section",
          text: { type: "mrkdwn", text: summaryText },
        },
      ],
    },
  };
}
