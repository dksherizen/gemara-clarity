import OpenAI from "openai";
import type { JSONCallOptions, LLMAdapter, LLMResult } from "./types.js";
import { extractJSON } from "./jsonparse.js";

export interface OpenAIAdapterConfig {
  apiKey: string;
  baseURL?: string;
  model?: string;
  provider?: "openai" | "lmstudio";
}

export class OpenAIAdapter implements LLMAdapter {
  readonly provider: "openai" | "lmstudio";
  readonly model: string;
  private client: OpenAI;

  constructor(cfg: OpenAIAdapterConfig) {
    this.provider = cfg.provider ?? "openai";
    this.model = cfg.model ?? (this.provider === "lmstudio" ? "local-model" : "gpt-5");
    this.client = new OpenAI({
      apiKey: cfg.apiKey || "lm-studio-no-key",
      baseURL: cfg.baseURL,
      dangerouslyAllowBrowser: typeof window !== "undefined",
    });
  }

  async callJSON<T = unknown>(opts: JSONCallOptions): Promise<LLMResult<T>> {
    const useStructuredOutput =
      this.provider === "openai" && opts.schema && opts.schemaName;

    // LM Studio only supports "json_schema" or "text" response_format.
    // OpenAI also supports "json_object". Pick based on provider.
    const responseFormat = useStructuredOutput
      ? {
          type: "json_schema" as const,
          json_schema: {
            name: opts.schemaName!,
            strict: false,
            schema: opts.schema as Record<string, unknown>,
          },
        }
      : this.provider === "lmstudio"
        ? { type: "text" as const }
        : { type: "json_object" as const };

    const buildRequest = (includeTemperature: boolean) => ({
      model: this.model,
      ...(includeTemperature ? { temperature: opts.temperature ?? 0.1 } : {}),
      max_completion_tokens: opts.maxTokens ?? 32000,
      messages: [
        { role: "system" as const, content: opts.system },
        { role: "user" as const, content: opts.user },
      ],
      response_format: responseFormat,
    });

    let resp;
    try {
      resp = await this.client.chat.completions.create(buildRequest(true));
    } catch (err) {
      const msg = (err as Error).message || "";
      if (
        msg.includes("temperature") &&
        msg.toLowerCase().includes("does not support")
      ) {
        resp = await this.client.chat.completions.create(buildRequest(false));
      } else {
        throw err;
      }
    }

    const choice = resp.choices[0];
    if (choice.finish_reason === "length") {
      throw new Error(
        `${this.provider} output truncated; increase maxTokens or split work.`,
      );
    }
    const text = choice.message.content ?? "";
    const data = extractJSON<T>(text);
    return {
      data,
      raw: text,
      usage: {
        inputTokens: resp.usage?.prompt_tokens,
        outputTokens: resp.usage?.completion_tokens,
      },
      provider: this.provider,
      model: this.model,
    };
  }
}
