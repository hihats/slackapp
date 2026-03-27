import { DefineDatastore, Schema } from "deno-slack-sdk/mod.ts";

/** ガイドライン「理解しました」の確認記録 */
export const ConfirmationResultsDatastore = DefineDatastore({
  name: "confirmation_results",
  primary_key: "id",
  attributes: {
    id: { type: Schema.types.string },
    timestamp: { type: Schema.types.string },
    user_id: { type: Schema.slack.types.user_id },
    user_name: { type: Schema.types.string },
  },
});
