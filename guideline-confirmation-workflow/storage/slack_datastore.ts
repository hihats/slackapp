import {
  ConfirmationRecord,
  QuizClearedRecord,
  QuizResultRecord,
  StorageProvider,
} from "./interface.ts";

// deno-lint-ignore no-explicit-any
type SlackClient = any;

export class SlackDatastoreProvider implements StorageProvider {
  private client: SlackClient;

  constructor(client: SlackClient) {
    this.client = client;
  }

  async saveConfirmation(record: ConfirmationRecord): Promise<void> {
    const id = `${record.userId}_${record.timestamp}`;
    const result = await this.client.apps.datastore.put({
      datastore: "confirmation_results",
      item: {
        id,
        timestamp: record.timestamp,
        user_id: record.userId,
        user_name: record.userName,
      },
    });

    if (!result.ok) {
      throw new Error(
        `Failed to save confirmation record: ${result.error}`,
      );
    }
  }

  async saveQuizResult(record: QuizResultRecord): Promise<void> {
    const id = `${record.userId}_${record.timestamp}`;
    const result = await this.client.apps.datastore.put({
      datastore: "quiz_results",
      item: {
        id,
        timestamp: record.timestamp,
        user_id: record.userId,
        user_name: record.userName,
        quiz_id: record.quizId,
        category: record.category,
        answer: record.answer,
        correct: record.correct,
      },
    });

    if (!result.ok) {
      throw new Error(
        `Failed to save quiz result: ${result.error}`,
      );
    }
  }

  async saveQuizCleared(record: QuizClearedRecord): Promise<void> {
    const id = `${record.userId}_${record.timestamp}`;
    const result = await this.client.apps.datastore.put({
      datastore: "quiz_cleared",
      item: {
        id,
        timestamp: record.timestamp,
        user_id: record.userId,
        user_name: record.userName,
        user_real_name: record.userRealName,
      },
    });

    if (!result.ok) {
      throw new Error(
        `Failed to save quiz cleared record: ${result.error}`,
      );
    }
  }
}
