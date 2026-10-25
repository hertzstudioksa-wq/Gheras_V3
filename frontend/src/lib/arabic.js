// Arabic number agreement for the few counts the pages print
// ("4 سنة" → "4 سنوات", "10 صورة" → "10 صور").

/** forms: [one, two, few (3–10), many (11+)]; `n` is printed before few/many. */
export function countLabel(n, [one, two, few, many]) {
  const k = Number(n) || 0;
  if (k === 1) return one;
  if (k === 2) return two;
  if (k >= 3 && k <= 10) return `${k} ${few}`;
  return `${k} ${many}`;
}

export const ageLabel = (n) => countLabel(n, ["سنة واحدة", "سنتان", "سنوات", "سنة"]);
export const imagesLabel = (n) => countLabel(n, ["صورة واحدة", "صورتان", "صور", "صورة"]);
export const pagesLabel = (n) => countLabel(n, ["صفحة واحدة", "صفحتان", "صفحات", "صفحة"]);
/** A category's topic count; none means the parent writes their own situation. */
export const topicsLabel = (n) => (Number(n) ? countLabel(n, ["موضوع واحد", "موضوعان", "مواضيع", "موضوعاً"]) : "موقف تكتبه بنفسك");
export const scenesLabel = (n) => countLabel(n, ["مشهد واحد", "مشهدان", "مشاهد", "مشهداً"]);
