// Mirrors backend app/core/market.py PLAYERS. The API rejects unknown slugs.
export const PLAYER_NAMES: Record<string, string> = {
  openai: "OpenAI",
  anthropic: "Anthropic",
  google: "Google / DeepMind",
  microsoft: "Microsoft",
  meta: "Meta",
  nvidia: "NVIDIA",
  xai: "xAI",
  amazon: "Amazon",
  alibaba: "Alibaba / Qwen",
  mistral: "Mistral",
  huggingface: "Hugging Face",
};

export function isKnownPlayer(slug: string): boolean {
  return Object.prototype.hasOwnProperty.call(PLAYER_NAMES, slug);
}
