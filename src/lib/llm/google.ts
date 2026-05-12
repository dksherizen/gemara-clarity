import { GoogleGenerativeAI } from "@google/generative-ai";
import type { JSONCallOptions, LLMAdapter, LLMResult } from "./types.js";
import { extractJSON } from "./jsonparse.js";

export interface GoogleAdapterConfig {
  apiKey: string;
  model?: string;
}

export class GoogleAdapter implements LLMAdapter {
  readonly provider = "google" as const;
  readonly model: string;
  private client: GoogleGenerativeAI;

  constructor(cfg: GoogleAdapterConfig) {
    this.client = new GoogleGenerativeAI(cfg.apiKey);
    this.model = cfg.model ?? "gemini-2.5-pro";
  }

  async callJSON<T = unknown>(opts: JSONCallOptions): Promise<LLMResult<T>> {
    const model = this.client.getGenerativeModel({
      model: this.model,
      systemInstruction: opts.system,
      generationConfig: {
        temperature: opts.temperature ?? 0.1,
        maxOutputTokens: opts.maxTokens ?? 16000,
        responseMimeType: "application/json",
      },
    });
    const result = await model.generateContent(opts.user);
    const text = result.response.text();
    const data = extractJSON<T>(text);
    return {
      data,
      raw: text,
      usage: {
        inputTokens: result.response.usageMetadata?.promptTokenCount,
        outputTokens: result.response.usageMetadata?.candidatesTokenCount,
      },
      provider: this.provider,
      model: this.model,
    };
  }
}
