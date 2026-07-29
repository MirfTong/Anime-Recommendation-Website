export const CONTENT_TYPES = [
  { value: "ANIME", label: "Anime", resultLabel: "anime" },
  { value: "MANGA", label: "Manga", resultLabel: "manga" },
  { value: "MANHWA", label: "Manhwa", resultLabel: "manhwa" },
  { value: "ALL", label: "All", resultLabel: "titles" },
];

const EMPTY_FILTERS = {
  q: "",
  min_score: "",
  min_year: "",
  max_year: "",
  min_episodes: "",
  min_chapters: "",
  min_volumes: "",
  type: "",
  season: "",
  status: "",
  genre: [],
  tag: [],
};

const PAGE_WINDOW_SIZE = 8;

export function filtersFor() {
  return {
    ...EMPTY_FILTERS,
    genre: [],
    tag: [],
  };
}

export const TOP_RATED_FILTERS = { ...filtersFor(), type: "TV" };

export function filtersMatch(left, right) {
  return Object.keys(EMPTY_FILTERS).every((key) => {
    if (!Array.isArray(left[key])) return left[key] === right[key];
    return left[key].length === right[key].length
      && left[key].every((value, index) => value === right[key][index]);
  });
}

export function queryString(filters, page = 1, contentType = "ANIME") {
  const params = new URLSearchParams({
    content_type: contentType,
    page: String(page),
    per_page: "24",
  });
  const commonKeys = ["q", "min_score", "min_year", "max_year", "genre", "tag"];
  const activeKeys = contentType === "ANIME"
    ? [...commonKeys, "min_episodes", "type", "season"]
    : contentType === "MANGA" || contentType === "MANHWA"
      ? [...commonKeys, "min_chapters", "min_volumes", "status"]
      : commonKeys;

  activeKeys.forEach((key) => {
    const value = filters[key];
    if (Array.isArray(value) ? value.length > 0 : value) {
      params.set(key, Array.isArray(value) ? value.join(",") : value);
    }
  });
  return params.toString();
}

export function contentTypeDetails(value) {
  return CONTENT_TYPES.find((contentType) => contentType.value === value)
    ?? CONTENT_TYPES[0];
}

export function itemContentType(item) {
  const value = item?.content_type?.toUpperCase();
  return CONTENT_TYPES.some(
    (contentType) => contentType.value === value && value !== "ALL",
  )
    ? value
    : "ANIME";
}

function formatSeason(season) {
  if (!season) return null;
  return `${season.charAt(0).toUpperCase()}${season.slice(1)}`;
}

function formatStatus(status) {
  if (!status) return null;
  return status
    .replaceAll("_", " ")
    .toLowerCase()
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

export function itemMetadata(item, detailed = false) {
  const contentType = itemContentType(item);
  const year = item.year ?? item.publication_year ?? "Unknown year";

  if (contentType === "ANIME") {
    return [
      item.type || "Anime",
      formatSeason(item.season),
      year,
      `${item.episodes ?? "?"} ${detailed ? "episodes" : "eps"}`,
    ].filter(Boolean);
  }

  return [
    contentTypeDetails(contentType).label,
    formatStatus(item.status),
    year,
    `${item.chapters ?? "?"} ${detailed ? "chapters" : "ch"}`,
    `${item.volumes ?? "?"} ${detailed ? "volumes" : "vols"}`,
  ].filter(Boolean);
}

export function visiblePageNumbers(currentPage, totalPages) {
  const windowSize = Math.min(PAGE_WINDOW_SIZE, totalPages);
  const halfWindow = Math.floor(windowSize / 2);
  const firstPage = Math.max(
    1,
    Math.min(currentPage - halfWindow, totalPages - windowSize + 1),
  );

  return Array.from({ length: windowSize }, (_, index) => firstPage + index);
}
