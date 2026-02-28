/** ガイドライン「理解しました」の確認記録 */
export interface ConfirmationRecord {
  timestamp: string;
  userId: string;
  userName: string;
}

/** 理解度テスト（クイズ）の回答記録 */
export interface QuizResultRecord {
  timestamp: string;
  userId: string;
  userName: string;
  quizId: string;
  category: string;
  answer: string;
  correct: boolean;
}

/** 理解度テスト全問正解（クリア）の記録 */
export interface QuizClearedRecord {
  timestamp: string;
  userId: string;
  userName: string;      // user.name（アカウント名）
  userRealName: string;  // user.real_name（表示名）
}

export interface StorageProvider {
  saveConfirmation(record: ConfirmationRecord): Promise<void>;
  saveQuizResult(record: QuizResultRecord): Promise<void>;
  saveQuizCleared(record: QuizClearedRecord): Promise<void>;
}
