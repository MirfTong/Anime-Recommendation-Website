export const CONTENT_TYPES = [
  { value: "ANIME", label: "Anime", resultLabel: "anime" },
  { value: "MANGA", label: "Manga", resultLabel: "manga" },
  { value: "MANHWA", label: "Manhwa", resultLabel: "manhwa" },
  { value: "ALL", label: "All", resultLabel: "titles" },
];

export const DEFAULT_SORT = "top_rated";

const EMPTY_FILTERS = {
  q: "",
  min_score: "",
  min_year: "",
  max_year: "",
  min_episodes: "",
  max_episodes: "",
  min_chapters: "",
  min_volumes: "",
  type: "",
  season: "",
  status: "",
  genre: [],
  tag: [],
};

const COMMON_FILTER_KEYS = [
  "q",
  "min_score",
  "min_year",
  "max_year",
  "genre",
  "tag",
];
const ANIME_FILTER_KEYS = [
  ...COMMON_FILTER_KEYS,
  "min_episodes",
  "max_episodes",
  "type",
  "season",
  "status",
];
const PRINT_FILTER_KEYS = [
  ...COMMON_FILTER_KEYS,
  "min_chapters",
  "min_volumes",
  "status",
];
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

export function scoreLabel(value) {
  if (value === null || value === undefined || value === "") return "?";
  const numericValue = Number(value);
  return Number.isFinite(numericValue) ? numericValue.toFixed(2) : "?";
}

export function usesTopRatedAnimeHomepage(
  contentType,
  filters,
  allTypesExplicitlySelected = false,
) {
  return contentType === "ANIME"
    && filtersMatch(filters, filtersFor())
    && !allTypesExplicitlySelected;
}

function filterKeysFor(contentType) {
  if (contentType === "ANIME") return ANIME_FILTER_KEYS;
  if (contentType === "MANGA" || contentType === "MANHWA") {
    return PRINT_FILTER_KEYS;
  }
  return COMMON_FILTER_KEYS;
}

function addFilterParams(params, filters, contentType) {
  filterKeysFor(contentType).forEach((key) => {
    const value = filters[key];
    if (Array.isArray(value) ? value.length > 0 : value) {
      params.set(key, Array.isArray(value) ? value.join(",") : value);
    }
  });
}

export function queryString(
  filters,
  page = 1,
  contentType = "ANIME",
  sort = DEFAULT_SORT,
) {
  const params = new URLSearchParams({
    content_type: contentType,
    page: String(page),
    per_page: "24",
    sort,
  });
  addFilterParams(params, filters, contentType);
  return params.toString();
}

export function catalogueUrlSearch({
  contentType = "ANIME",
  filters = filtersFor(),
  page = 1,
  sort = DEFAULT_SORT,
  view = "results",
} = {}) {
  const params = new URLSearchParams();
  if (contentType !== "ANIME") params.set("content_type", contentType);
  if (page > 1) params.set("page", String(page));
  if (sort !== DEFAULT_SORT) params.set("sort", sort);
  if (view === "home") {
    params.set("view", "home");
  } else {
    addFilterParams(params, filters, contentType);
  }
  const value = params.toString();
  return value ? `?${value}` : "";
}

function commaSeparatedValues(params, key) {
  return params
    .getAll(key)
    .flatMap((value) => value.split(","))
    .map((value) => value.trim())
    .filter(Boolean)
    .filter((value, index, values) => values.indexOf(value) === index);
}

export function catalogueStateFromSearch(search = "") {
  const params = new URLSearchParams(search);
  const requestedContentType = (params.get("content_type") ?? "ANIME").toUpperCase();
  const contentType = CONTENT_TYPES.some(({ value }) => value === requestedContentType)
    ? requestedContentType
    : "ANIME";
  const validSortValues = sortOptionsFor(contentType).map(({ value }) => value);
  const requestedSort = params.get("sort") ?? DEFAULT_SORT;
  const sort = validSortValues.includes(requestedSort) ? requestedSort : DEFAULT_SORT;
  const requestedPage = Number(params.get("page") ?? 1);
  const page = Number.isInteger(requestedPage) && requestedPage > 0
    ? requestedPage
    : 1;
  const view = params.get("view") === "home" && contentType === "ANIME"
    ? "home"
    : "results";
  const filters = filtersFor();
  if (view !== "home") {
    filterKeysFor(contentType).forEach((key) => {
      filters[key] = Array.isArray(filters[key])
        ? commaSeparatedValues(params, key)
        : params.get(key) ?? "";
    });
  }
  const hasState = [...params.keys()].some((key) => (
    [
      "content_type",
      "page",
      "sort",
      "view",
      ...filterKeysFor(contentType),
    ].includes(key)
  ));
  return {
    contentType,
    filters,
    page,
    sort,
    view: hasState ? view : "home",
    hasState,
  };
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
      formatStatus(item.status),
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

export function sortOptionsFor(contentType) {
  const options = [
    { value: "top_rated", label: "Top rated" },
    { value: "newest", label: "Newest release" },
    { value: "oldest", label: "Oldest release" },
    { value: "title", label: "A–Z" },
  ];
  if (contentType === "ANIME") {
    options.push({ value: "most_episodes", label: "Most episodes" });
  } else if (contentType === "MANGA" || contentType === "MANHWA") {
    options.push({ value: "most_chapters", label: "Most chapters" });
  }
  return options;
}

function currentSeason(now) {
  const seasons = ["winter", "spring", "summer", "fall"];
  return seasons[Math.floor(now.getMonth() / 3)];
}

export function presetsFor(contentType, now = new Date()) {
  const presets = [];
  if (contentType === "ANIME") {
    presets.push(
      {
        id: "new-season",
        label: "New this season",
        filters: {
          type: "TV",
          status: "CURRENTLY_AIRING",
          season: currentSeason(now),
          min_year: String(now.getFullYear()),
          max_year: String(now.getFullYear()),
        },
      },
      {
        id: "short-series",
        label: "Short series",
        filters: { type: "TV", max_episodes: "13" },
      },
      {
        id: "movies",
        label: "Movies",
        filters: { type: "MOVIE" },
      },
    );
  }
  presets.push({
    id: "highly-rated",
    label: "Highly rated",
    filters: { min_score: "8" },
  });
  if (contentType === "MANGA") {
    presets.push({
      id: "completed-manga",
      label: "Completed manga",
      filters: { status: "FINISHED" },
    });
  }
  if (contentType === "MANHWA") {
    presets.push({
      id: "ongoing-manhwa",
      label: "Ongoing manhwa",
      filters: { status: "PUBLISHING" },
    });
  }
  return presets;
}

export function filtersFromPreset(preset) {
  return {
    ...filtersFor(),
    ...preset.filters,
  };
}

export function activeFilterChips(filters, contentType) {
  const chips = [];
  filters.genre.forEach((value) => {
    chips.push({ key: "genre", value, label: value });
  });
  filters.tag.forEach((value) => {
    chips.push({ key: "tag", value, label: `Tag: ${value}` });
  });
  const scalarLabels = {
    type: (value) => `Type: ${value}`,
    season: (value) => `Season: ${formatSeason(value)}`,
    min_score: (value) => `Score: ${value}+`,
    min_year: (value) => `From: ${value}`,
    max_year: (value) => `To: ${value}`,
    status: (value) => `Status: ${formatStatus(value)}`,
    min_episodes: (value) => `Episodes: ${value}+`,
    max_episodes: (value) => `Episodes: up to ${value}`,
    min_chapters: (value) => `Chapters: ${value}+`,
    min_volumes: (value) => `Volumes: ${value}+`,
  };
  filterKeysFor(contentType).forEach((key) => {
    if (
      key !== "q"
      && !Array.isArray(filters[key])
      && filters[key]
      && scalarLabels[key]
    ) {
      chips.push({ key, value: filters[key], label: scalarLabels[key](filters[key]) });
    }
  });
  return chips;
}

export function filtersWithoutChip(filters, chip) {
  const nextFilters = {
    ...filters,
    genre: [...filters.genre],
    tag: [...filters.tag],
  };
  if (Array.isArray(nextFilters[chip.key])) {
    nextFilters[chip.key] = nextFilters[chip.key].filter(
      (value) => value !== chip.value,
    );
  } else if (Object.hasOwn(nextFilters, chip.key)) {
    nextFilters[chip.key] = "";
  }
  return nextFilters;
}

export function validatedPage(value, totalPages) {
  const page = Number(value);
  return Number.isInteger(page) && page >= 1 && page <= totalPages
    ? page
    : null;
}

export function responsiveFilterPanelClasses(mobileOpen, moreOpen) {
  return [
    mobileOpen ? "grid" : "hidden",
    moreOpen ? "sm:grid" : "sm:hidden",
    "gap-3 sm:col-span-2 sm:grid-cols-2 lg:col-span-6 lg:grid-cols-6",
  ].join(" ");
}

export function formatFreshness(timestamp, now = new Date()) {
  if (!timestamp) return null;
  const updated = new Date(timestamp);
  if (Number.isNaN(updated.getTime())) return null;
  const elapsedMinutes = Math.max(
    0,
    Math.floor((now.getTime() - updated.getTime()) / 60_000),
  );
  if (elapsedMinutes < 1) return "Catalogue updated just now";
  if (elapsedMinutes < 60) {
    return `Catalogue updated ${elapsedMinutes} minute${elapsedMinutes === 1 ? "" : "s"} ago`;
  }
  const elapsedHours = Math.floor(elapsedMinutes / 60);
  if (elapsedHours < 24) {
    return `Catalogue updated ${elapsedHours} hour${elapsedHours === 1 ? "" : "s"} ago`;
  }
  const elapsedDays = Math.floor(elapsedHours / 24);
  return `Catalogue updated ${elapsedDays} day${elapsedDays === 1 ? "" : "s"} ago`;
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
