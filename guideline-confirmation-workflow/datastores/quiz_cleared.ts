import { DefineDatastore, Schema } from "deno-slack-sdk/mod.ts";

/** 理解度テスト全問正解（クリア）の記録 */
export const QuizClearedDatastore = DefineDatastore({
  name: "quiz_cleared",
  primary_key: "id",
  attributes: {
    id: { type: Schema.types.string },
    timestamp: { type: Schema.types.string },
    user_id: { type: Schema.slack.types.user_id },
    user_name: { type: Schema.types.string },
    user_real_name: { type: Schema.types.string },
  },
});
