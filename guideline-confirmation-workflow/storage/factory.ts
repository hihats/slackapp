import { StorageProvider } from "./interface.ts";
import { SlackDatastoreProvider } from "./slack_datastore.ts";
import { SpreadsheetProvider } from "./spreadsheet.ts";

// deno-lint-ignore no-explicit-any
type SlackClient = any;

/**
 * 環境変数 STORAGE_TYPE に応じてストレージ実装を切り替える。
 *
 * - "slack_datastore" (デフォルト): Slack Datastore に記録
 * - "spreadsheet": Google Spreadsheet に Webhook 経由で記録
 */
export function createStorageProvider(
  env: Record<string, string>,
  client: SlackClient,
): StorageProvider {
  const storageType = env.STORAGE_TYPE || "slack_datastore";

  switch (storageType) {
    case "spreadsheet":
      return new SpreadsheetProvider(env.SPREADSHEET_WEBHOOK_URL || "");
    case "slack_datastore":
    default:
      return new SlackDatastoreProvider(client);
  }
}
