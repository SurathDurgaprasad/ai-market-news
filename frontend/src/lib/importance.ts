export type ImportanceKey = "major" | "significant" | "notable" | "minor";

export type ImageRole = "hero" | "source" | "none";

export function importanceMeta(score: number): {
  key: ImportanceKey;
  label: string;
  badge: string;
  card: string;
  accent: string;
  image: string;
  title: string;
} {
  if (score >= 90) {
    return {
      key: "major",
      label: "Major",
      badge: "text-warning",
      card: "border-line",
      accent: "before:absolute before:inset-y-0 before:left-0 before:w-0.5 before:bg-warning",
      image: "aspect-[16/8] max-h-44",
      title: "text-[1.45rem] leading-[1.18] md:text-[1.55rem]",
    };
  }
  if (score >= 70) {
    return {
      key: "significant",
      label: "Significant",
      badge: "text-secondary",
      card: "border-line",
      accent: "before:absolute before:inset-y-0 before:left-0 before:w-0.5 before:bg-accent",
      image: "aspect-[16/9] max-h-40",
      title: "text-[1.3rem] leading-[1.2]",
    };
  }
  if (score >= 50) {
    return {
      key: "notable",
      label: "Notable",
      badge: "text-muted",
      card: "border-line",
      accent: "",
      image: "aspect-[16/10] max-h-36",
      title: "text-[1.15rem] leading-[1.22]",
    };
  }
  return {
    key: "minor",
    label: "Minor",
    badge: "text-muted",
    card: "border-line",
    accent: "",
    image: "",
    title: "text-[1.05rem] leading-[1.25]",
  };
}

export function entityPreview(entities: string[] | undefined, limit = 3): {
  shown: string[];
  remainder: number;
} {
  const list = (entities ?? []).map((item) => item.trim()).filter(Boolean);
  return {
    shown: list.slice(0, limit),
    remainder: Math.max(0, list.length - limit),
  };
}

export function shouldShowCardImage(
  imageUrl: string | undefined,
  imageRole: ImageRole | undefined,
  importance: ImportanceKey,
): boolean {
  if (!imageUrl) return false;
  if (imageRole === "none") return false;
  if (importance === "minor") return false;
  return true;
}
