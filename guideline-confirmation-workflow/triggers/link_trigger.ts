import { Trigger } from "deno-slack-api/types.ts";
import { TriggerTypes } from "deno-slack-api/mod.ts";
import { GuidelineConfirmationWorkflow } from "../workflows/guideline_confirmation_workflow.ts";

/**
 * リンクトリガー: 生成された URL を社員に共有して利用する。
 *
 * 作成コマンド:
 *   slack trigger create --trigger-def triggers/link_trigger.ts
 */
const TOOL_NAME = Deno.env.get("TOOL_NAME");
if (!TOOL_NAME) {
  throw new Error("TOOL_NAME is not set. Run: export TOOL_NAME=<ツール名>");
}
const linkTrigger: Trigger<
  typeof GuidelineConfirmationWorkflow.definition
> = {
  type: TriggerTypes.Shortcut,
  name: `${TOOL_NAME}利用ガイドライン確認`,
  description: `利用開始前に、ガイドラインをご理解いただき、理解度テストにご回答ください。正解いただいた方からアカウント発行されます。ワークフロー開始前に下記URLからご確認ください。https://crowdworks.slack.com/docs/T0291TDHV/F0AFE7BAUJK`,
  workflow:
    `#/workflows/${GuidelineConfirmationWorkflow.definition.callback_id}`,
  inputs: {
    interactivity: { value: "{{data.interactivity}}" },
    user_id: { value: "{{data.user_id}}" },
  },
};

export default linkTrigger;
