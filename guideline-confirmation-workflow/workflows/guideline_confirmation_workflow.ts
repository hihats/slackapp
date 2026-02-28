import { DefineWorkflow, Schema } from "deno-slack-sdk/mod.ts";
import { GuidelineConfirmationFunction } from "../functions/guideline_confirmation.ts";

export const GuidelineConfirmationWorkflow = DefineWorkflow({
  callback_id: "guideline_confirmation_workflow",
  title: "ガイドライン確認ワークフロー",
  description:
    "ガイドラインの既読確認を行い、理解度クイズに回答してもらいます",
  input_parameters: {
    properties: {
      interactivity: { type: Schema.slack.types.interactivity },
      user_id: { type: Schema.slack.types.user_id },
    },
    required: ["interactivity", "user_id"],
  },
});

GuidelineConfirmationWorkflow.addStep(GuidelineConfirmationFunction, {
  interactivity: GuidelineConfirmationWorkflow.inputs.interactivity,
  user_id: GuidelineConfirmationWorkflow.inputs.user_id,
});
