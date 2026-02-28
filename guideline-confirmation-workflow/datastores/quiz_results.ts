import { DefineDatastore, Schema } from "deno-slack-sdk/mod.ts";

/** 理解度テスト（クイズ）の回答記録 */
export const QuizResultsDatastore = DefineDatastore({
  name: "quiz_results",
  primary_key: "id",
  attributes: {
    id: { type: Schema.types.string },
    timestamp: { type: Schema.types.string },
    user_id: { type: Schema.slack.types.user_id },
    user_name: { type: Schema.types.string },
    quiz_id: { type: Schema.types.string },
    category: { type: Schema.types.string },
    answer: { type: Schema.types.string },
    correct: { type: Schema.types.boolean },
  },
});
