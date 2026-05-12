import { AnthropicAdapter } from "./anthropic.js";
import { OpenAIAdapter } from "./openai.js";
import { GoogleAdapter } from "./google.js";
import type { JSONCallOptions, LLMAdapter, LLMResult, PipelinePass, Provider } from "./types.js";

// USD per million tokens, approximate. Update as pricing changes.
const PRICING: Record<string, { input: number; output: number }> = {
  "claude-opus-4-7": { input: 15, output: 75 },
  "claude-sonnet-4-6": { input: 3, output: 15 },
  "claude-haiku-4-5": { input: 1, output: 5 },
  "gpt-5": { input: 1.25, output: 10 },
  "gpt-5-mini": { input: 0.25, output: 2 },
  "gpt-5-nano": { input: 0.05, output: 0.4 },
  "gpt-5.1": { input: 1.5, output: 12 },
  "gpt-5.2": { input: 1.75, output: 14 },
  "gpt-5.4": { input: 2, output: 16 },
  "gpt-5.5": { input: 2.5, output: 20 },
  "gpt-5-pro": { input: 15, output: 75 },
  "gemini-2.5-pro": { input: 1.25, output: 10 },
  "gemini-2.5-flash": { input: 0.3, output: 2.5 },
};

function priceFor(model: string): { input: number; output: number } {
  // try exact, then prefix match (e.g. "gpt-5.2-2025-12-11" → "gpt-5.2")
  if (PRICING[model]) return PRICING[model];
  for (const key of Object.keys(PRICING)) {
    if (model.startsWith(key)) return PRICING[key];
  }
  return { input: 0, output: 0 };
}

export interface RouterConfig {
  anthropicKey?: string;
  openaiKey?: string;
  googleKey?: string;
  anthropicModel?: string;
  openaiModel?: string;
  googleModel?: string;
  lmstudioBaseURL?: string;
  lmstudioModel?: string;
  passProviders?: Partial<Record<PipelinePass, Provider>>;
}

const DEFAULT_PROVIDER_FOR_PASS: Record<PipelinePass, Provider> = {
  segmentation: "anthropic",
  structure: "anthropic",
  phrasemap: "lmstudio",
  meforshim: "anthropic",
  teaching: "lmstudio",
  validate: "openai",
};

export interface UsageRecord {
  provider: Provider;
  model: string;
  inputTokens: number;
  outputTokens: number;
  estimatedUSD: number;
  pass?: PipelinePass;
}

export class LLMRouter {
  private adapters: Partial<Record<Provider, LLMAdapter>> = {};
  private passMap: Record<PipelinePass, Provider>;
  public usage: UsageRecord[] = [];

  constructor(cfg: RouterConfig) {
    this.passMap = { ...DEFAULT_PROVIDER_FOR_PASS, ...cfg.passProviders };
    if (cfg.anthropicKey) {
      this.adapters.anthropic = new AnthropicAdapter({
        apiKey: cfg.anthropicKey,
        model: cfg.anthropicModel,
      });
    }
    if (cfg.openaiKey) {
      this.adapters.openai = new OpenAIAdapter({
        apiKey: cfg.openaiKey,
        model: cfg.openaiModel,
      });
    }
    if (cfg.googleKey) {
      this.adapters.google = new GoogleAdapter({
        apiKey: cfg.googleKey,
        model: cfg.googleModel,
      });
    }
    if (cfg.lmstudioBaseURL) {
      this.adapters.lmstudio = new OpenAIAdapter({
        apiKey: "lm-studio",
        baseURL: cfg.lmstudioBaseURL,
        model: cfg.lmstudioModel ?? "local-model",
        provider: "lmstudio",
      });
    }
  }

  for(pass: PipelinePass): LLMAdapter {
    const requested = this.passMap[pass];
    const adapter = this.adapters[requested];
    if (adapter) return this.wrap(adapter, pass);
    const fallback = this.fallbackOrder(requested)
      .map((p) => this.adapters[p])
      .find(Boolean);
    if (!fallback) {
      throw new Error(
        `No LLM adapter configured. Pass '${pass}' wanted '${requested}' but no providers are available. Set ANTHROPIC_API_KEY / OPENAI_API_KEY / GOOGLE_API_KEY / LMSTUDIO_BASE_URL.`,
      );
    }
    return this.wrap(fallback, pass);
  }

  private wrap(inner: LLMAdapter, pass: PipelinePass): LLMAdapter {
    const router = this;
    return {
      provider: inner.provider,
      model: inner.model,
      async callJSON<T = unknown>(opts: JSONCallOptions): Promise<LLMResult<T>> {
        const result = await inner.callJSON<T>(opts);
        const price = priceFor(inner.model);
        const inputT = result.usage?.inputTokens ?? 0;
        const outputT = result.usage?.outputTokens ?? 0;
        const estimatedUSD =
          inner.provider === "lmstudio"
            ? 0
            : (inputT * price.input + outputT * price.output) / 1_000_000;
        router.usage.push({
          provider: inner.provider,
          model: inner.model,
          inputTokens: inputT,
          outputTokens: outputT,
          estimatedUSD,
          pass,
        });
        return result;
      },
    };
  }

  totalCost(): number {
    return this.usage.reduce((s, u) => s + u.estimatedUSD, 0);
  }

  costByPass(): Record<string, number> {
    const out: Record<string, number> = {};
    for (const u of this.usage) {
      const k = u.pass ?? "unknown";
      out[k] = (out[k] ?? 0) + u.estimatedUSD;
    }
    return out;
  }

  resetUsage(): void {
    this.usage = [];
  }

  private fallbackOrder(preferred: Provider): Provider[] {
    const all: Provider[] = ["anthropic", "openai", "google", "lmstudio"];
    return [preferred, ...all.filter((p) => p !== preferred)];
  }

  availableProviders(): Provider[] {
    return Object.keys(this.adapters) as Provider[];
  }
}
