import { DefineFunction, Schema, SlackFunction } from "deno-slack-sdk/mod.ts";
import { getQuizById, getRandomQuizzes } from "../data/quiz_loader.ts";
import { buildGuidelineView } from "./views/guideline_view.ts";
import { buildQuizView, PreviousResult, QuizViewMetadata } from "./views/quiz_view.ts";
import { buildCorrectResultView } from "./views/result_view.ts";
import {
  recordConfirmation,
  recordQuizCleared,
  recordQuizResult,
} from "./operations/record_and_notify.ts";

const TOTAL_QUESTIONS = 3;

export const GuidelineConfirmationFunction = DefineFunction({
  callback_id: "guideline_confirmation",
  title: "ガイドライン確認チェック",
  description: "ガイドライン確認と理解度テストをモーダルで実施し、結果を記録する",
  source_file: "functions/guideline_confirmation.ts",
  input_parameters: {
    properties: {
      interactivity: { type: Schema.slack.types.interactivity },
      user_id: { type: Schema.slack.types.user_id },
    },
    required: ["interactivity", "user_id"],
  },
  output_parameters: {
    properties: {
      quiz_id: { type: Schema.types.string },
      correct: { type: Schema.types.boolean },
    },
    required: ["quiz_id", "correct"],
  },
});

// --- Phase 1: モーダルを開く ---
export default SlackFunction(
  GuidelineConfirmationFunction,
  async ({ inputs, client }) => {
    const result = await client.views.open(
      buildGuidelineView(inputs.interactivity.interactivity_pointer),
    );
    if (!result.ok) {
      return { error: `Failed to open modal: ${result.error}` };
    }
    return { completed: false };
  },
)
  // --- Phase 2: 「理解しました」submit → 確認記録 → クイズ1問目に切替 ---
  .addViewSubmissionHandler(
    "guideline_view",
    async ({ body, client, env }) => {
      await recordConfirmation({
        userId: body.user.id,
        client,
        env,
      });
      const quizzes = getRandomQuizzes(TOTAL_QUESTIONS);
      const firstQuiz = quizzes[0];
      const metadata: QuizViewMetadata = {
        quiz_id: firstQuiz.id,
        question_number: 1,
        total_questions: TOTAL_QUESTIONS,
        remaining_quiz_ids: quizzes.slice(1).map((q) => q.id),
        failed_quiz_ids: [],
      };
      return { response_action: "update", view: buildQuizView(firstQuiz, metadata) };
    },
  )
  // --- Phase 3: クイズ回答 submit → 正誤判定・記録・次の問題 or 再出題 or 完了 ---
  .addViewSubmissionHandler(
    "quiz_view",
    async ({ view, body, client, env }) => {
      const metadata: QuizViewMetadata = JSON.parse(view.private_metadata || "{}");
      const quiz = getQuizById(metadata.quiz_id);
      const blockId = `quiz_answer_block_${metadata.quiz_id}`;
      const answerValue =
        view.state.values[blockId]?.quiz_answer.selected_option?.value;

      if (!quiz || !answerValue) return;

      const isCorrect = answerValue === quiz.correctValue;

      await recordQuizResult({
        userId: body.user.id,
        quizId: quiz.id,
        category: quiz.category,
        answer: answerValue,
        isCorrect,
        client,
        env,
      });

      // 不正解なら失敗リストに追加
      const failedQuizIds = [...(metadata.failed_quiz_ids || [])];
      if (!isCorrect) {
        failedQuizIds.push(quiz.id);
      }

      // 前問の解説情報を構築
      const correctLabel = !isCorrect
        ? quiz.choices.find((c) => c.value === quiz.correctValue)?.label ?? ""
        : undefined;
      const previousResult: PreviousResult = {
        correct: isCorrect,
        category: quiz.category,
        question: quiz.question,
        explanation: quiz.explanation,
        correctLabel,
      };

      // 残りの問題があれば次へ
      if (metadata.remaining_quiz_ids.length > 0) {
        const nextQuizId = metadata.remaining_quiz_ids[0];
        const nextQuiz = getQuizById(nextQuizId);
        if (nextQuiz) {
          const nextMetadata: QuizViewMetadata = {
            quiz_id: nextQuiz.id,
            question_number: metadata.question_number + 1,
            total_questions: metadata.total_questions,
            remaining_quiz_ids: metadata.remaining_quiz_ids.slice(1),
            failed_quiz_ids: failedQuizIds,
            is_retry_round: metadata.is_retry_round,
            previous_result: previousResult,
          };
          return { response_action: "update", view: buildQuizView(nextQuiz, nextMetadata) };
        }
      }

      // ラウンド終了 — 不正解の問題があれば再出題
      if (failedQuizIds.length > 0) {
        const firstRetryQuiz = getQuizById(failedQuizIds[0]);
        if (firstRetryQuiz) {
          const retryMetadata: QuizViewMetadata = {
            quiz_id: firstRetryQuiz.id,
            question_number: 1,
            total_questions: failedQuizIds.length,
            remaining_quiz_ids: failedQuizIds.slice(1),
            failed_quiz_ids: [],
            is_retry_round: true,
            previous_result: previousResult,
          };
          return { response_action: "update", view: buildQuizView(firstRetryQuiz, retryMetadata) };
        }
      }

      // 全問正解 → クリア記録 → 完了
      await recordQuizCleared({
        userId: body.user.id,
        client,
        env,
      });
      await client.functions.completeSuccess({
        function_execution_id: body.function_data.execution_id,
        outputs: { quiz_id: quiz.id, correct: true },
      });
      return buildCorrectResultView(quiz);
    },
  )
  // --- モーダルが閉じられた場合 ---
  .addViewClosedHandler(
    ["guideline_view", "quiz_view"],
    async ({ body, client }) => {
      await client.functions.completeError({
        function_execution_id: body.function_data.execution_id,
        error: "User closed the modal",
      });
    },
  );
