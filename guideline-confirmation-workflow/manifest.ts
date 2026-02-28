import { Manifest } from "deno-slack-sdk/mod.ts";
import { GuidelineConfirmationWorkflow } from "./workflows/guideline_confirmation_workflow.ts";
import { ConfirmationResultsDatastore } from "./datastores/confirmation_results.ts";
import { QuizClearedDatastore } from "./datastores/quiz_cleared.ts";
import { QuizResultsDatastore } from "./datastores/quiz_results.ts";

export default Manifest({
  name: "guideline-confirmation",
  description:
    "ガイドラインの既読確認とランダムクイズで理解度を記録するワークフロー",
  icon: "assets/icon.png",
  workflows: [GuidelineConfirmationWorkflow],
  datastores: [ConfirmationResultsDatastore, QuizResultsDatastore, QuizClearedDatastore],
  outgoingDomains: [
    // Spreadsheet 連携を使う場合のみ必要
    "script.google.com",
  ],
  botScopes: [
    "commands",
    "chat:write",
    "datastore:read",
    "datastore:write",
    "users:read",
    "canvases:read",
  ],
});
