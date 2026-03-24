import {
  ConfirmationRecord,
  QuizClearedRecord,
  QuizResultRecord,
  StorageProvider,
} from "./interface.ts";

/**
 * Google Spreadsheet への記録を Google Apps Script Webhook 経由で行う。
 *
 * セットアップ手順:
 * 1. Google Spreadsheet を作成し、3つのシートを用意:
 *    - 「確認記録」シート: timestamp | user_id | user_name
 *    - 「テスト結果」シート: timestamp | user_id | user_name | quiz_id | category | answer | correct
 *    - 「テストクリア」シート: timestamp | user_id | user_name | user_real_name
 * 2. Apps Script (スクリプトエディタ) に以下を実装:
 *    function doPost(e) {
 *      const ss = SpreadsheetApp.getActiveSpreadsheet();
 *      const data = JSON.parse(e.postData.contents);
 *      if (data.type === "confirmation") {
 *        const sheet = ss.getSheetByName("確認記録");
 *        sheet.appendRow([data.timestamp, data.userId, data.userName]);
 *      } else if (data.type === "quiz_cleared") {
 *        const sheet = ss.getSheetByName("テストクリア");
 *        sheet.appendRow([data.timestamp, data.userId, data.userName, data.userRealName]);
 *      } else {
 *        const sheet = ss.getSheetByName("テスト結果");
 *        sheet.appendRow([
 *          data.timestamp, data.userId, data.userName,
 *          data.quizId, data.category, data.answer, data.correct
 *        ]);
 *      }
 *      return ContentService.createTextOutput("ok");
 *    }
 * 3. ウェブアプリとしてデプロイし、URL を取得
 * 4. slack env add SPREADSHEET_WEBHOOK_URL <取得したURL>
 */
export class SpreadsheetProvider implements StorageProvider {
  private webhookUrl: string;

  constructor(webhookUrl: string) {
    if (!webhookUrl) {
      throw new Error(
        "SPREADSHEET_WEBHOOK_URL is required for SpreadsheetProvider",
      );
    }
    this.webhookUrl = webhookUrl;
  }

  async saveConfirmation(record: ConfirmationRecord): Promise<void> {
    const response = await fetch(this.webhookUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ type: "confirmation", ...record }),
    });

    if (!response.ok) {
      throw new Error(
        `Failed to save confirmation to spreadsheet: ${response.status} ${response.statusText}`,
      );
    }
  }

  async saveQuizResult(record: QuizResultRecord): Promise<void> {
    const response = await fetch(this.webhookUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ type: "quiz_result", ...record }),
    });

    if (!response.ok) {
      throw new Error(
        `Failed to save quiz result to spreadsheet: ${response.status} ${response.statusText}`,
      );
    }
  }

  async saveQuizCleared(record: QuizClearedRecord): Promise<void> {
    const response = await fetch(this.webhookUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ type: "quiz_cleared", ...record }),
    });

    if (!response.ok) {
      throw new Error(
        `Failed to save quiz cleared to spreadsheet: ${response.status} ${response.statusText}`,
      );
    }
  }
}
