import { onCall, HttpsError } from "firebase-functions/v2/https";
import { defineSecret } from "firebase-functions/params";
import { initializeApp } from "firebase-admin/app";
import { getFirestore, FieldValue } from "firebase-admin/firestore";
import OpenAI from "openai";

initializeApp();

const OPENAI_API_KEY = defineSecret("OPENAI_API_KEY");

const ALLOWED_MODELS = new Set([
  "gpt-5.5",
  "gpt-5.5-thinking",
  "gpt-5.5-pro",
  "gpt-5",
  "gpt-5-turbo",
  "gpt-4o",
  "gpt-4o-mini",
]);

type ChatRequest = {
  model: string;
  messages: Array<{ role: "system" | "user" | "assistant"; content: string }>;
  temperature?: number;
  max_tokens?: number;
  response_format?: { type: "text" | "json_object" };
};

export const openaiChat = onCall(
  {
    secrets: [OPENAI_API_KEY],
    region: "us-central1",
    enforceAppCheck: false,
    maxInstances: 10,
  },
  async (request) => {
    if (!request.auth) {
      throw new HttpsError("unauthenticated", "Sign in required.");
    }

    const data = request.data as ChatRequest;
    if (!data?.model || !Array.isArray(data?.messages) || data.messages.length === 0) {
      throw new HttpsError("invalid-argument", "model and messages are required.");
    }
    if (!ALLOWED_MODELS.has(data.model)) {
      throw new HttpsError("invalid-argument", `Model not allowed: ${data.model}`);
    }

    const client = new OpenAI({ apiKey: OPENAI_API_KEY.value() });

    const completion = await client.chat.completions.create({
      model: data.model,
      messages: data.messages,
      temperature: data.temperature,
      max_tokens: data.max_tokens,
      response_format: data.response_format,
    });

    const usage = completion.usage;
    if (usage) {
      await getFirestore()
        .collection("usage")
        .doc(request.auth.uid)
        .collection("openai")
        .add({
          model: data.model,
          prompt_tokens: usage.prompt_tokens,
          completion_tokens: usage.completion_tokens,
          total_tokens: usage.total_tokens,
          at: FieldValue.serverTimestamp(),
        })
        .catch(() => {
          // usage logging is best-effort; never fail the request because of it
        });
    }

    return {
      id: completion.id,
      model: completion.model,
      choices: completion.choices,
      usage: completion.usage,
    };
  }
);
