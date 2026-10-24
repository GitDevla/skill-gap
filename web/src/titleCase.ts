const MINOR_WORDS = new Set(["a", "an", "and", "as", "at", "by", "for", "from", "in", "into", "of", "on", "or", "the", "to", "via", "with"]);

export function formatTitleCase(label: string): string {
  return label
    .split(" ")
    .map((word, i) => {
      if (word !== word.toLowerCase() || (i > 0 && MINOR_WORDS.has(word))) return word;
      return word.replace(/(^\P{L}*|-)(\p{L})/gu, (_, prefix: string, letter: string) => prefix + letter.toUpperCase());
    })
    .join(" ");
}
