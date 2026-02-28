import { createStorageProvider } from "../../storage/factory.ts";

// deno-lint-ignore no-explicit-any
type SlackClient = any;

interface UserNames {
  name: string;      // user.name（アカウント名）
  realName: string;  // user.real_name（表示名）
}

/** ユーザーのアカウント名と表示名を解決する */
export async function resolveUserNames(
  client: SlackClient,
  userId: string,
): Promise<UserNames> {
  const userInfo = await client.users.info({ user: userId });
  if (userInfo.ok) {
    return {
      name: userInfo.user.name || userId,
      realName: userInfo.user.real_name || userInfo.user.name || userId,
    };
  }
  return { name: userId, realName: userId };
}

interface RecordConfirmationParams {
  userId: string;
  client: SlackClient;
  env: Record<string, string>;
}

/**
 * ガイドライン「理解しました」の確認記録
 */
export async function recordConfirmation(
  params: RecordConfirmationParams,
): Promise<void> {
  const { userId, client, env } = params;
  const { realName } = await resolveUserNames(client, userId);
  const storage = createStorageProvider(env, client);

  try {
    await storage.saveConfirmation({
      timestamp: new Date().toISOString(),
      userId,
      userName: realName,
    });
  } catch (err) {
    console.error("Failed to save confirmation record:", err);
  }
}

interface RecordQuizClearedParams {
  userId: string;
  client: SlackClient;
  env: Record<string, string>;
}

/**
 * 理解度テスト全問正解（クリア）の記録 + 管理者通知
 */
export async function recordQuizCleared(
  params: RecordQuizClearedParams,
): Promise<void> {
  const { userId, client, env } = params;
  const { name, realName } = await resolveUserNames(client, userId);
  const storage = createStorageProvider(env, client);

  try {
    await storage.saveQuizCleared({
      timestamp: new Date().toISOString(),
      userId,
      userName: name,
      userRealName: realName,
    });
  } catch (err) {
    console.error("Failed to save quiz cleared record:", err);
  }

  const adminChannel = env.ADMIN_CHANNEL;
  if (adminChannel) {
    await client.chat.postMessage({
      channel: adminChannel,
      text: `${TOOL_NAME}ガイドライン確認: <@${userId}> — 理解度テストをクリアしました`,
    });
  }

  // 指定ユーザーにDM通知（設定されている場合）
  const notifyUserId = env.NOTIFY_USER_ID;
  if (notifyUserId) {
    await client.chat.postMessage({
      channel: notifyUserId,
      text: `${TOOL_NAME}ガイドライン確認: ${name}（${realName}）が理解度テストをクリアしました`,
    });
  }
}

interface RecordQuizResultParams {
  userId: string;
  quizId: string;
  category: string;
  answer: string;
  isCorrect: boolean;
  client: SlackClient;
  env: Record<string, string>;
}

/**
 * クイズ回答後の業務処理: ユーザー名解決 → Datastore 記録 → 管理者通知
 */
export async function recordQuizResult(
  params: RecordQuizResultParams,
): Promise<void> {
  const { userId, quizId, category, answer, isCorrect, client, env } = params;
  const { realName } = await resolveUserNames(client, userId);
  const storage = createStorageProvider(env, client);

  try {
    await storage.saveQuizResult({
      timestamp: new Date().toISOString(),
      userId,
      userName: realName,
      quizId,
      category,
      answer,
      correct: isCorrect,
    });
  } catch (err) {
    console.error("Failed to save quiz result:", err);
  }

  // 管理者チャンネルに通知（設定されている場合）
  const adminChannel = env.ADMIN_CHANNEL;
  if (adminChannel) {
    await client.chat.postMessage({
      channel: adminChannel,
      text: `ガイドライン確認: <@${userId}> — 理解度テスト ${isCorrect ? "正解" : "不正解"} [${category}]`,
    });
  }
}
