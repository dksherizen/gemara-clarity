import Anthropic from "@anthropic-ai/sdk";
import type { JSONCallOptions, LLMAdapter, LLMResult } from "./types.js";
import { extractJSON } from "./jsonparse.js";

export interface AnthropicAdapterConfig {
  apiKey: string;
  model?: string;
}

export class AnthropicAdapter implements LLMAdapter {
  readonly provider = "anthropic" as const;
  readonly model: string;
  private client: Anthropic;

  constructor(cfg: AnthropicAdapterConfig) {
    this.client = new Anthropic({ apiKey: cfg.apiKey });
    this.model = cfg.model ?? "claude-opus-4-7";
  }

  async callJSON<T = unknown>(opts: JSONCallOptions): Promise<LLMResult<T>> {
    const schemaHint = opts.schema
      ? `\n\nReturn ONLY a single JSON object that conforms to this schema (no commentary, no markdown fences):\n${JSON.stringify(
          opts.schema,
        )}`
      : "\n\nReturn ONLY a single JSON object (no commentary, no markdown fences).";

    const buildRequest = (includeTemperature: boolean) => ({
      model: this.model,
      max_tokens: opts.maxTokens ?? 16000,
      ...(includeTemperature ? { temperature: opts.temperature ?? 0.1 } : {}),
      system: opts.system + schemaHint,
      messages: [{ role: "user" as const, content: opts.user }],
    });

    let resp;
    try {
      resp = await this.client.messages.create(buildRequest(true));
    } catch (err) {
      const msg = (err as Error).message || "";
      if (msg.includes("temperature") && (msg.includes("deprecated") || msg.includes("does not support") || msg.includes("not supported"))) {
        resp = await this.client.messages.create(buildRequest(false));
      } else {
        throw err;
      }
    }

    const text = resp.content
      .filter((b): b is Anthropic.TextBlock => b.type === "text")
      .map((b) => b.text)
      .join("\n");
    const data = extractJSON<T>(text);
    return {
      data,
      raw: text,
      usage: {
        inputTokens: resp.usage.input_tokens,
        outputTokens: resp.usage.output_tokens,
      },
      provider: this.provider,
      model: this.model,
    };
  }
}
