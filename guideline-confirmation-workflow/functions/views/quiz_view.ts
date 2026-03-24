import { Quiz } from "../../data/quiz_loader.ts";

/** 前の問題の正誤・解説情報 */
export interface PreviousResult {
  correct: boolean;
  category: string;
  question: string;
  explanation: string;
  correctLabel?: string; // 不正解時の正解選択肢
}

export interface QuizViewMetadata {
  quiz_id: string;
  question_number: number;
  total_questions: number;
  remaining_quiz_ids: string[];
  failed_quiz_ids: string[];
  is_retry_round?: boolean;
  previous_result?: PreviousResult;
}

export function buildQuizView(quiz: Quiz, metadata: QuizViewMetadata) {
  // deno-lint-ignore no-explicit-any
  const blocks: any[] = [];

  // 前の問題の解説を表示
  if (metadata.previous_result) {
    const prev = metadata.previous_result;
    const resultText = prev.correct
      ? ":white_check_mark: *正解！*"
      : `:x: *不正解*（正解: ${prev.correctLabel}）`;

    blocks.push(
      {
        type: "section",
        text: { type: "mrkdwn", text: resultText },
      },
      {
        type: "context",
        elements: [
          { type: "mrkdwn", text: `*${prev.category}*: ${prev.question}` },
        ],
      },
      {
        type: "section",
        text: { type: "mrkdwn", text: prev.explanation },
      },
      { type: "divider" },
    );
  }

  // 今回の問題
  blocks.push(
    {
      type: "context",
      elements: [
        { type: "mrkdwn", text: `カテゴリ: *${quiz.category}*` },
      ],
    },
    {
      type: "section",
      text: { type: "mrkdwn", text: quiz.question },
    },
    {
      type: "input",
      block_id: `quiz_answer_block_${quiz.id}`,
      label: {
        type: "plain_text" as const,
        text: "回答を選択してください",
      },
      element: {
        type: "radio_buttons" as const,
        action_id: "quiz_answer",
        options: quiz.choices.map((choice) => ({
          text: { type: "plain_text" as const, text: choice.label },
          value: choice.value,
        })),
      },
    },
  );

  // private_metadata にはprevious_resultを含めない（次の問題には不要）
  const { previous_result: _, ...metadataForStorage } = metadata;

  return {
    type: "modal" as const,
    callback_id: "quiz_view",
    title: {
      type: "plain_text" as const,
      text: metadata.is_retry_round
        ? `理解度テスト（追試） ${metadata.question_number}/${metadata.total_questions}`
        : `理解度テスト ${metadata.question_number}/${metadata.total_questions}`,
    },
    submit: { type: "plain_text" as const, text: "回答する" },
    close: { type: "plain_text" as const, text: "閉じる" },
    private_metadata: JSON.stringify(metadataForStorage),
    blocks,
  };
}
