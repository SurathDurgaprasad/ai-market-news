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
      badge: "text-amber-400",
      card: "border-amber-400/35 bg-[#14120e]",
      accent: "before:absolute before:inset-y-0 before:left-0 before:w-[2px] before:bg-amber-400",
      image: "aspect-[16/8] max-h-44",
      title: "text-[1.35rem] leading-snug md:text-[1.45rem]",
    };
  }
  if (score >= 70) {
    return {
      key: "significant",
      label: "Significant",
      badge: "text-sky-400",
      card: "border-sky-400/30",
      accent: "before:absolute before:inset-y-0 before:left-0 before:w-[2px] before:bg-sky-400",
      image: "aspect-[16/9] max-h-40",
      title: "text-[1.2rem] leading-snug",
    };
  }
  if (score >= 50) {
    return {
      key: "notable",
      label: "Notable",
      badge: "text-sky-300/90",
      card: "border-white/[0.08]",
      accent: "",
      image: "aspect-[16/10] max-h-36",
      title: "text-[1.05rem] leading-snug",
    };
  }
  return {
    key: "minor",
    label: "Minor",
    badge: "text-zinc-500",
    card: "border-white/[0.06] bg-[#0d0d0f]",
    accent: "",
    image: "",
    title: "text-[0.98rem] leading-snug text-zinc-200",
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

export function cardImageClass(
  imageRole: ImageRole | undefined,
  importanceFallback: string,
): string {
  if (imageRole === "hero") return "aspect-[16/8] max-h-44";
  if (imageRole === "source") return "aspect-[16/10] max-h-[8.25rem]";
  return importanceFallback;
}

export function detailImageClass(imageRole: ImageRole | undefined): string {
  if (imageRole === "hero") return "aspect-[21/6] max-h-[180px]";
  return "aspect-[21/5] max-h-[120px]";
}
