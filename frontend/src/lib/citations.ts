export function stripWrappingQuotes(text: string | null | undefined): string {
  let cleaned = (text ?? "").trim();
  const pairs: Array<[string, string]> = [
    ['"', '"'],
    ["'", "'"],
    ["\u201c", "\u201d"],
    ["\u2018", "\u2019"],
    ["\u00ab", "\u00bb"],
    ["\u201e", "\u201c"],
  ];

  let guard = 0;
  while (cleaned.length >= 2 && guard < 6) {
    guard += 1;
    const match = pairs.find(
      ([start, end]) =>
        cleaned.startsWith(start) &&
        cleaned.endsWith(end) &&
        cleaned.length > start.length + end.length,
    );
    if (!match) break;
    const inner = cleaned.slice(match[0].length, cleaned.length - match[1].length).trim();
    if (!inner) break;
    cleaned = inner;
  }
  return cleaned;
}

export function formatCitation(text: string | null | undefined): string {
  const inner = stripWrappingQuotes(text);
  return inner ? `\u201c${inner}\u201d` : "";
}
