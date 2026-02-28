export interface QuizChoice {
  label: string;
  value: string;
}

export interface Quiz {
  id: string;
  category: string;
  question: string;
  choices: QuizChoice[];
  correctValue: string;
  explanation: string;
}

import quizzesJson from "./quizzes.json" with { type: "json" };

const quizzes: Quiz[] = quizzesJson;

export function getRandomQuiz(): Quiz {
  return quizzes[Math.floor(Math.random() * quizzes.length)];
}

/** 指定数のユニークなクイズをランダムに取得 */
export function getRandomQuizzes(count: number): Quiz[] {
  const shuffled = [...quizzes].sort(() => Math.random() - 0.5);
  return shuffled.slice(0, Math.min(count, shuffled.length));
}

export function getQuizById(id: string): Quiz | undefined {
  return quizzes.find((q) => q.id === id);
}

export function getAllQuizzes(): Quiz[] {
  return [...quizzes];
}
