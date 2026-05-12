export type Provider = "anthropic" | "openai" | "google" | "lmstudio";

export type PipelinePass =
  | "segmentation"
  | "structure"
  | "phrasemap"
  | "meforshim"
  | "teaching"
  | "validate";

export interface LLMMessage {
  role: "system" | "user" | "assistant";
  content: string;
}

export interface JSONCallOptions {
  system: string;
  user: string;
  schema?: Record<string, unknown>;
  schemaName?: string;
  maxTokens?: number;
  temperature?: number;
  thinking?: boolean;
}

export interface LLMResult<T = unknown> {
  data: T;
  raw: string;
  usage?: { inputTokens?: number; outputTokens?: number };
  provider: Provider;
  model: string;
}

export interface LLMAdapter {
  provider: Provider;
  model: string;
  callJSON<T = unknown>(opts: JSONCallOptions): Promise<LLMResult<T>>;
}
