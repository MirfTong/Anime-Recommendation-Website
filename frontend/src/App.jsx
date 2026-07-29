import { useCallback, useEffect, useRef, useState } from "react";
import {
  CONTENT_TYPES,
  DEFAULT_SORT,
  TOP_RATED_FILTERS,
  activeFilterChips,
  catalogueStateFromSearch,
  catalogueUrlSearch,
  contentTypeDetails,
  filtersFor,
  filtersFromPreset,
  filtersMatch,
  filtersWithoutChip,
  formatFreshness,
  itemContentType,
  itemMetadata,
  presetsFor,
  queryString,
  responsiveFilterPanelClasses,
  scoreLabel,
  sortOptionsFor,
  usesTopRatedAnimeHomepage,
  validatedPage,
  visiblePageNumbers,
} from "./catalogue.js";

function Score({ value }) {
  return (
    <span className="rounded-full bg-amber-300/15 px-2.5 py-1 text-sm font-bold text-amber-300">
      ★ {scoreLabel(value)}
    </span>
  );
}

function ContentBadge({ contentType }) {
  const styles = {
    ANIME: "bg-violet-500/90 text-white",
    MANGA: "bg-emerald-400/90 text-slate-950",
    MANHWA: "bg-sky-400/90 text-slate-950",
  };
  return (
    <span
      className={`rounded-full px-2.5 py-1 text-[0.65rem] font-black uppercase tracking-widest ${
        styles[contentType] ?? styles.ANIME
      }`}
    >
      {contentTypeDetails(contentType).label}
    </span>
  );
}

function CatalogueCard({ item, onSelect, showContentBadge = false }) {
  const metadata = itemMetadata(item).join(" · ");
  const cardContentType = itemContentType(item);

  return (
    <button
      className="group flex h-full min-w-0 flex-col overflow-hidden rounded-2xl border border-white/10 bg-slate-900/80 text-left shadow-lg transition hover:-translate-y-1 hover:border-violet-400/60 hover:shadow-glow focus:outline-none focus:ring-2 focus:ring-violet-400"
      onClick={() => onSelect(item)}
      type="button"
    >
      <div className="relative aspect-[2/3] w-full shrink-0 overflow-hidden bg-slate-800">
        <img
          className="block h-full w-full object-cover object-center transition duration-300 group-hover:scale-105"
          src={item.image_url}
          alt={`${item.title} cover`}
          loading="lazy"
        />
        {showContentBadge && (
          <div className="absolute right-3 top-3">
            <ContentBadge contentType={cardContentType} />
          </div>
        )}
        <div className="absolute bottom-3 left-3"><Score value={item.score} /></div>
      </div>
      <div className="flex flex-1 flex-col space-y-2 p-4">
        <h2 className="line-clamp-2 min-h-12 text-base font-bold text-white">
          {item.title}
        </h2>
        <p
          className="overflow-hidden text-ellipsis whitespace-nowrap text-xs tracking-tight text-slate-400"
          title={metadata}
        >
          {metadata}
        </p>
        <div className="mt-auto flex min-h-7 flex-wrap gap-1.5">
          {(item.genres ?? []).slice(0, 3).map((genre) => (
            <span
              key={genre}
              className="rounded-full bg-violet-400/10 px-2 py-1 text-xs text-violet-200"
            >
              {genre}
            </span>
          ))}
        </div>
      </div>
    </button>
  );
}

function DetailModal({ item, loading, onClose }) {
  if (!item) return null;

  const contentType = itemContentType(item);
  const tags = item.genres_detailed ?? item.tags ?? [];
  const freshness = formatFreshness(item.last_jikan_sync);

  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-slate-950/85 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label={item.title}
      aria-busy={loading}
    >
      <article className="relative max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-3xl border border-white/10 bg-slate-900 shadow-2xl">
        <button
          className="absolute right-4 top-4 rounded-full bg-slate-950/80 px-3 py-1 text-xl text-white hover:bg-violet-600"
          onClick={onClose}
          type="button"
          aria-label="Close details"
        >
          &times;
        </button>
        <div className="grid gap-6 p-6 sm:grid-cols-[12rem_1fr]">
          <img
            className="w-full rounded-2xl object-cover"
            src={item.image_url}
            alt={`${item.title} cover`}
          />
          <div className="space-y-4">
            <div>
              <p className="text-sm font-semibold uppercase tracking-widest text-violet-300">
                {contentTypeDetails(contentType).label} details
              </p>
              <h2 className="mt-1 text-3xl font-black text-white">{item.title}</h2>
              {item.alternative_title && (
                <p className="mt-1 text-slate-400">{item.alternative_title}</p>
              )}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Score value={item.score} />
              <span className="text-slate-300">{itemMetadata(item, true).join(" · ")}</span>
            </div>
            <div className="flex flex-wrap gap-2">
              {(item.genres ?? []).map((genre) => (
                <span
                  key={genre}
                  className="rounded-full bg-violet-400/10 px-3 py-1 text-sm text-violet-100"
                >
                  {genre}
                </span>
              ))}
            </div>
            {loading && (
              <p className="text-sm text-violet-200" role="status">
                Loading full details…
              </p>
            )}
            {item.synopsis && (
              <section>
                <h3 className="text-sm font-semibold uppercase tracking-widest text-violet-300">
                  Synopsis
                </h3>
                <p className="mt-2 whitespace-pre-line text-sm leading-6 text-slate-300">
                  {item.synopsis}
                </p>
              </section>
            )}
            {tags.length > 0 && (
              <p className="text-sm leading-6 text-slate-400">Tags: {tags.join(", ")}</p>
            )}
            {freshness && (
              <p
                className="text-xs text-slate-500"
                title={new Date(item.last_jikan_sync).toLocaleString()}
              >
                {freshness}
              </p>
            )}
            {item.mal_url && (
              <a
                className="inline-flex rounded-xl bg-violet-500 px-4 py-2 font-bold text-white transition hover:bg-violet-400"
                href={item.mal_url}
                target="_blank"
                rel="noreferrer"
              >
                View on MyAnimeList ↗
              </a>
            )}
          </div>
        </div>
      </article>
    </div>
  );
}

function GenreTagPicker({
  filters,
  genres,
  tagOptions,
  tagQuery,
  tagsLoading,
  dropdownOpen,
  dropdownRef,
  onDropdownToggle,
  onQueryChange,
  onGenreToggle,
  onTagToggle,
}) {
  const matchingGenres = genres.filter((genre) => (
    genre.toLowerCase().includes(tagQuery.trim().toLowerCase())
  ));
  return (
    <div className="relative">
      <details
        ref={dropdownRef}
        className="group"
        onToggle={(event) => onDropdownToggle(event.currentTarget.open)}
      >
        <summary className="filter-input flex cursor-pointer list-none items-center justify-between marker:hidden">
          {dropdownOpen ? (
            <input
              className="min-w-0 flex-1 bg-transparent text-sm text-white outline-none placeholder:text-slate-400"
              value={tagQuery}
              onChange={(event) => onQueryChange(event.target.value)}
              onClick={(event) => event.stopPropagation()}
              placeholder="Search genres and tags"
              aria-label="Search genres and tags"
              autoFocus
            />
          ) : (
            <span>
              {filters.genre.length + filters.tag.length
                ? `${filters.genre.length + filters.tag.length} selected`
                : "All genres & tags"}
            </span>
          )}
          <span className="text-violet-300 transition group-open:rotate-180">⌄</span>
        </summary>
        <div className="absolute z-30 mt-2 max-h-72 w-full min-w-64 overflow-y-auto rounded-xl border border-white/10 bg-slate-950 p-1 shadow-2xl">
          <p className="px-3 pb-1 pt-2 text-xs font-bold uppercase tracking-widest text-violet-300">
            Genres
          </p>
          {matchingGenres.map((genre) => (
            <button
              key={genre}
              className={`block w-full rounded-lg px-3 py-2 text-left text-sm transition ${
                filters.genre.includes(genre)
                  ? "bg-violet-500 text-white"
                  : "text-slate-300 hover:bg-violet-400/10"
              }`}
              type="button"
              aria-pressed={filters.genre.includes(genre)}
              onClick={() => onGenreToggle(genre)}
            >
              {genre}
            </button>
          ))}
          <p className="mt-2 border-t border-white/10 px-3 pb-1 pt-3 text-xs font-bold uppercase tracking-widest text-violet-300">
            Tags
          </p>
          {tagsLoading ? (
            <p className="px-3 py-2 text-sm text-slate-400">Searching tags…</p>
          ) : tagOptions.map((tag) => (
            <button
              key={tag}
              className={`block w-full rounded-lg px-3 py-2 text-left text-sm capitalize transition ${
                filters.tag.includes(tag)
                  ? "bg-violet-500 text-white"
                  : "text-slate-300 hover:bg-violet-400/10"
              }`}
              type="button"
              aria-pressed={filters.tag.includes(tag)}
              onClick={() => onTagToggle(tag)}
            >
              {tag}
            </button>
          ))}
          {!tagsLoading && tagOptions.length === 50 && (
            <p className="px-3 py-2 text-xs text-slate-400">
              Showing the first 50 matching tags. Keep typing to narrow the list.
            </p>
          )}
        </div>
      </details>
    </div>
  );
}

export default function App() {
  const initialStateRef = useRef(catalogueStateFromSearch(window.location.search));
  const initialState = initialStateRef.current;
  const initialAppliedFilters = initialState.view === "home"
    ? TOP_RATED_FILTERS
    : initialState.filters;

  const [contentType, setContentType] = useState(initialState.contentType);
  const [filters, setFilters] = useState(initialState.filters);
  const [appliedFilters, setAppliedFilters] = useState(initialAppliedFilters);
  const [sort, setSort] = useState(initialState.sort);
  const [allTypesExplicitlySelected, setAllTypesExplicitlySelected] = useState(
    initialState.view === "results" && initialState.contentType === "ANIME",
  );
  const [genres, setGenres] = useState([]);
  const [tagOptions, setTagOptions] = useState([]);
  const [tagQuery, setTagQuery] = useState("");
  const [tagsLoading, setTagsLoading] = useState(false);
  const [genreDropdownOpen, setGenreDropdownOpen] = useState(false);
  const [mobileFiltersOpen, setMobileFiltersOpen] = useState(false);
  const [moreFiltersOpen, setMoreFiltersOpen] = useState(false);
  const [activePreset, setActivePreset] = useState("");
  const [items, setItems] = useState([]);
  const [seasonalAnime, setSeasonalAnime] = useState([]);
  const [pagination, setPagination] = useState({
    page: initialState.page,
    pages: 1,
    total: 0,
  });
  const [seasonalPagination, setSeasonalPagination] = useState({
    page: 1,
    pages: 1,
    total: 0,
  });
  const [updatedAt, setUpdatedAt] = useState(null);
  const [jumpPage, setJumpPage] = useState("");
  const [pageError, setPageError] = useState("");
  const [loading, setLoading] = useState(true);
  const [seasonalLoading, setSeasonalLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [viewMode, setViewMode] = useState(initialState.view);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState(null);
  const genreDropdownRef = useRef(null);
  const catalogueRequestRef = useRef(0);
  const genreRequestRef = useRef(0);
  const tagRequestRef = useRef(0);
  const detailRequestRef = useRef(0);

  const loadCatalogue = useCallback(async (
    page = 1,
    activeFilters = TOP_RATED_FILTERS,
    activeContentType = "ANIME",
    activeSort = DEFAULT_SORT,
  ) => {
    const requestId = ++catalogueRequestRef.current;
    setLoading(true);
    setError("");
    try {
      const response = await fetch(
        `/api/v1/catalogue?${queryString(
          activeFilters,
          page,
          activeContentType,
          activeSort,
        )}`,
      );
      const body = await response.json();
      if (!response.ok) {
        const label = contentTypeDetails(activeContentType).resultLabel;
        throw new Error(body.error?.message || `Could not load ${label}.`);
      }
      if (requestId !== catalogueRequestRef.current) return;
      setItems(body.items ?? []);
      setPagination(body.pagination ?? { page: 1, pages: 1, total: 0 });
      setUpdatedAt(body.updated_at ?? null);
    } catch (requestError) {
      if (requestId !== catalogueRequestRef.current) return;
      setItems([]);
      setPagination({ page: 1, pages: 1, total: 0 });
      setUpdatedAt(null);
      setError(requestError.message);
    } finally {
      if (requestId === catalogueRequestRef.current) setLoading(false);
    }
  }, []);

  const updateUrl = useCallback((state, replace = false) => {
    const search = catalogueUrlSearch(state);
    const nextUrl = `${window.location.pathname}${search}`;
    window.history[replace ? "replaceState" : "pushState"]({}, "", nextUrl);
  }, []);

  const navigateCatalogue = useCallback(({
    page,
    activeFilters,
    activeContentType,
    activeSort,
    activeView,
    replace = false,
  }) => {
    updateUrl({
      page,
      filters: activeView === "home" ? filtersFor() : activeFilters,
      contentType: activeContentType,
      sort: activeSort,
      view: activeView,
    }, replace);
    loadCatalogue(page, activeFilters, activeContentType, activeSort);
  }, [loadCatalogue, updateUrl]);

  const loadSeasonalAnime = useCallback(async (page = 1) => {
    setSeasonalLoading(true);
    try {
      const response = await fetch(`/api/v1/anime/seasonal?limit=6&page=${page}`);
      const body = await response.json();
      if (!response.ok) {
        throw new Error(body.error?.message || "Could not load seasonal anime.");
      }
      setSeasonalAnime(body.items ?? []);
      setSeasonalPagination(
        body.pagination ?? { page: 1, pages: 1, total: body.items?.length ?? 0 },
      );
    } catch {
      setSeasonalAnime([]);
      setSeasonalPagination({ page: 1, pages: 1, total: 0 });
    } finally {
      setSeasonalLoading(false);
    }
  }, []);

  const loadGenres = useCallback(async (activeContentType) => {
    const requestId = ++genreRequestRef.current;
    try {
      const params = new URLSearchParams({ content_type: activeContentType });
      const response = await fetch(`/api/v1/genres?${params}`);
      const body = await response.json();
      if (!response.ok) throw new Error("Could not load genres.");
      if (requestId === genreRequestRef.current) setGenres(body.items ?? []);
    } catch {
      if (requestId === genreRequestRef.current) setGenres([]);
    }
  }, []);

  const loadTags = useCallback(async (query = "", activeContentType = "ANIME") => {
    const requestId = ++tagRequestRef.current;
    setTagsLoading(true);
    try {
      const params = new URLSearchParams({
        content_type: activeContentType,
        limit: "50",
      });
      if (query) params.set("q", query);
      const response = await fetch(`/api/v1/tags?${params}`);
      const body = await response.json();
      if (!response.ok) throw new Error(body.error?.message || "Could not load tags.");
      if (requestId === tagRequestRef.current) setTagOptions(body.items ?? []);
    } catch {
      if (requestId === tagRequestRef.current) setTagOptions([]);
    } finally {
      if (requestId === tagRequestRef.current) setTagsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadCatalogue(
      initialState.page,
      initialAppliedFilters,
      initialState.contentType,
      initialState.sort,
    );
    loadSeasonalAnime();
  }, [
    initialAppliedFilters,
    initialState.contentType,
    initialState.page,
    initialState.sort,
    loadCatalogue,
    loadSeasonalAnime,
  ]);

  useEffect(() => {
    const restoreFromUrl = () => {
      const restored = catalogueStateFromSearch(window.location.search);
      const restoredApplied = restored.view === "home"
        ? TOP_RATED_FILTERS
        : restored.filters;
      ++detailRequestRef.current;
      setContentType(restored.contentType);
      setFilters(restored.filters);
      setAppliedFilters(restoredApplied);
      setSort(restored.sort);
      setViewMode(restored.view);
      setAllTypesExplicitlySelected(
        restored.view === "results" && restored.contentType === "ANIME",
      );
      setActivePreset("");
      setSelected(null);
      setDetailLoading(false);
      setJumpPage("");
      setPageError("");
      loadCatalogue(
        restored.page,
        restoredApplied,
        restored.contentType,
        restored.sort,
      );
    };
    window.addEventListener("popstate", restoreFromUrl);
    return () => window.removeEventListener("popstate", restoreFromUrl);
  }, [loadCatalogue]);

  useEffect(() => {
    setGenres([]);
    loadGenres(contentType);
  }, [contentType, loadGenres]);

  useEffect(() => {
    const closeGenreDropdown = (event) => {
      if (!genreDropdownRef.current?.contains(event.target)) {
        genreDropdownRef.current?.removeAttribute("open");
      }
    };
    document.addEventListener("pointerdown", closeGenreDropdown);
    return () => document.removeEventListener("pointerdown", closeGenreDropdown);
  }, []);

  useEffect(() => {
    if (!genreDropdownOpen) return undefined;
    const timer = window.setTimeout(
      () => loadTags(tagQuery.trim(), contentType),
      200,
    );
    return () => window.clearTimeout(timer);
  }, [contentType, genreDropdownOpen, loadTags, tagQuery]);

  const defaultFilters = filtersFor();
  const hasSelections = !filtersMatch(filters, defaultFilters);
  const defaultViewMode = contentType === "ANIME" ? "home" : "results";
  const showHomepageSections = contentType === "ANIME" && viewMode === "home";
  const contentDetails = contentTypeDetails(contentType);
  const chips = showHomepageSections
    ? []
    : activeFilterChips(appliedFilters, contentType);
  const freshness = formatFreshness(updatedAt);
  const filterPresets = presetsFor(contentType);

  const submitFilters = (event) => {
    event.preventDefault();
    const submittedFilters = {
      ...filters,
      genre: [...filters.genre],
      tag: [...filters.tag],
    };
    const returnsHome = usesTopRatedAnimeHomepage(
      contentType,
      filters,
      allTypesExplicitlySelected,
    );
    const requestFilters = returnsHome ? TOP_RATED_FILTERS : submittedFilters;
    const nextView = returnsHome ? "home" : "results";
    setAppliedFilters(requestFilters);
    setViewMode(nextView);
    setActivePreset("");
    setMobileFiltersOpen(false);
    setJumpPage("");
    setPageError("");
    navigateCatalogue({
      page: 1,
      activeFilters: requestFilters,
      activeContentType: contentType,
      activeSort: sort,
      activeView: nextView,
    });
  };

  const selectContentType = (nextContentType) => {
    if (nextContentType === contentType) return;

    const nextFilters = filtersFor();
    const nextView = nextContentType === "ANIME" ? "home" : "results";
    const nextAppliedFilters = nextView === "home"
      ? TOP_RATED_FILTERS
      : nextFilters;
    ++detailRequestRef.current;
    setContentType(nextContentType);
    setFilters(nextFilters);
    setAppliedFilters(nextAppliedFilters);
    setSort(DEFAULT_SORT);
    setAllTypesExplicitlySelected(false);
    setSelected(null);
    setDetailLoading(false);
    setTagQuery("");
    setTagOptions([]);
    setTagsLoading(false);
    setActivePreset("");
    setMobileFiltersOpen(false);
    setMoreFiltersOpen(false);
    setJumpPage("");
    setPageError("");
    ++tagRequestRef.current;
    setGenreDropdownOpen(false);
    genreDropdownRef.current?.removeAttribute("open");
    setViewMode(nextView);
    navigateCatalogue({
      page: 1,
      activeFilters: nextAppliedFilters,
      activeContentType: nextContentType,
      activeSort: DEFAULT_SORT,
      activeView: nextView,
    });
  };

  const showRandom = async () => {
    const requestId = ++catalogueRequestRef.current;
    setViewMode("random");
    setLoading(true);
    setError("");
    setActivePreset("");
    try {
      const params = new URLSearchParams({ content_type: contentType, limit: "6" });
      const response = await fetch(`/api/v1/catalogue/random?${params}`);
      const body = await response.json();
      if (!response.ok) {
        throw new Error(
          body.error?.message || `Could not load random ${contentDetails.resultLabel}.`,
        );
      }
      if (requestId !== catalogueRequestRef.current) return;
      const randomItems = body.items ?? [];
      setItems(randomItems);
      setPagination({ page: 1, pages: 1, total: randomItems.length });
      setUpdatedAt(null);
    } catch (requestError) {
      if (requestId !== catalogueRequestRef.current) return;
      setItems([]);
      setPagination({ page: 1, pages: 1, total: 0 });
      setUpdatedAt(null);
      setError(requestError.message);
    } finally {
      if (requestId === catalogueRequestRef.current) setLoading(false);
    }
  };

  const openDetail = async (item) => {
    const requestId = ++detailRequestRef.current;
    const detailContentType = itemContentType(item);
    setSelected({ ...item, content_type: detailContentType });
    setDetailLoading(true);
    setError("");
    try {
      const response = await fetch(
        `/api/v1/catalogue/${detailContentType}/${item.mal_id}`,
      );
      const body = await response.json();
      if (!response.ok) {
        throw new Error(body.error?.message || "Could not load details.");
      }
      if (requestId === detailRequestRef.current) {
        setSelected({
          ...body.item,
          content_type: body.item?.content_type ?? detailContentType,
        });
      }
    } catch (requestError) {
      if (requestId !== detailRequestRef.current) return;
      setSelected(null);
      setError(requestError.message);
    } finally {
      if (requestId === detailRequestRef.current) setDetailLoading(false);
    }
  };

  const closeDetail = () => {
    ++detailRequestRef.current;
    setSelected(null);
    setDetailLoading(false);
  };

  const changeFilter = (event) => {
    if (event.target.name === "type") setAllTypesExplicitlySelected(true);
    setActivePreset("");
    setFilters((current) => ({
      ...current,
      [event.target.name]: event.target.value,
    }));
  };

  const toggleGenre = (genre) => {
    setActivePreset("");
    setFilters((current) => ({
      ...current,
      genre: current.genre.includes(genre)
        ? current.genre.filter((selectedGenre) => selectedGenre !== genre)
        : [...current.genre, genre],
    }));
  };

  const toggleTag = (tag) => {
    setActivePreset("");
    setFilters((current) => ({
      ...current,
      tag: current.tag.includes(tag)
        ? current.tag.filter((selectedTag) => selectedTag !== tag)
        : [...current.tag, tag],
    }));
  };

  const clearSelections = () => {
    const clearedFilters = filtersFor();
    const clearedAppliedFilters = contentType === "ANIME"
      ? TOP_RATED_FILTERS
      : clearedFilters;
    const nextView = contentType === "ANIME" ? "home" : "results";
    setFilters(clearedFilters);
    setAppliedFilters(clearedAppliedFilters);
    setAllTypesExplicitlySelected(false);
    setActivePreset("");
    setSort(DEFAULT_SORT);
    setMobileFiltersOpen(false);
    setMoreFiltersOpen(false);
    setJumpPage("");
    setPageError("");
    setViewMode(nextView);
    navigateCatalogue({
      page: 1,
      activeFilters: clearedAppliedFilters,
      activeContentType: contentType,
      activeSort: DEFAULT_SORT,
      activeView: nextView,
    });
  };

  const applyPreset = (preset) => {
    const presetFilters = filtersFromPreset(preset);
    setFilters(presetFilters);
    setAppliedFilters(presetFilters);
    setAllTypesExplicitlySelected(contentType === "ANIME");
    setActivePreset(preset.id);
    setViewMode("results");
    setMobileFiltersOpen(false);
    setJumpPage("");
    setPageError("");
    navigateCatalogue({
      page: 1,
      activeFilters: presetFilters,
      activeContentType: contentType,
      activeSort: sort,
      activeView: "results",
    });
  };

  const removeChip = (chip) => {
    const nextFilters = filtersWithoutChip(appliedFilters, chip);
    setFilters(nextFilters);
    setAppliedFilters(nextFilters);
    setActivePreset("");
    setAllTypesExplicitlySelected(contentType === "ANIME");
    setViewMode("results");
    navigateCatalogue({
      page: 1,
      activeFilters: nextFilters,
      activeContentType: contentType,
      activeSort: sort,
      activeView: "results",
    });
  };

  const changeSort = (event) => {
    const nextSort = event.target.value;
    const nextFilters = showHomepageSections ? filtersFor() : appliedFilters;
    setSort(nextSort);
    setFilters(nextFilters);
    setAppliedFilters(nextFilters);
    setViewMode("results");
    setAllTypesExplicitlySelected(contentType === "ANIME");
    setActivePreset("");
    navigateCatalogue({
      page: 1,
      activeFilters: nextFilters,
      activeContentType: contentType,
      activeSort: nextSort,
      activeView: "results",
    });
  };

  const goToPage = (page) => {
    setJumpPage("");
    setPageError("");
    navigateCatalogue({
      page,
      activeFilters: appliedFilters,
      activeContentType: contentType,
      activeSort: sort,
      activeView: showHomepageSections ? "home" : "results",
    });
  };

  const submitPageJump = (event) => {
    event.preventDefault();
    const page = validatedPage(jumpPage, pagination.pages);
    if (page === null) {
      setPageError(`Enter a page from 1 to ${pagination.pages}.`);
      return;
    }
    goToPage(page);
  };

  return (
    <main className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
      <header className="mb-8 flex flex-col gap-6 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="font-semibold uppercase tracking-[0.3em] text-violet-300">
            Discover your next favorite story
          </p>
          <h1 className="mt-2 text-4xl font-black tracking-tight text-white sm:text-6xl">
            KyoQuan
          </h1>
          <p className="mt-3 max-w-xl text-slate-300">
            Search a living catalogue of anime, manga, and manhwa.
          </p>
        </div>
        <button
          className="rounded-xl bg-white px-5 py-3 font-bold text-slate-950 transition hover:bg-violet-200"
          onClick={showRandom}
          type="button"
        >
          Randomize {contentType === "ALL" ? "All" : contentDetails.label}
        </button>
      </header>

      <div
        className="mb-4 grid grid-cols-2 gap-2 rounded-2xl border border-white/10 bg-slate-900/70 p-2 sm:grid-cols-4"
        role="group"
        aria-label="Catalogue content type"
      >
        {CONTENT_TYPES.map((option) => (
          <button
            key={option.value}
            className={`rounded-xl px-4 py-2.5 text-sm font-bold transition ${
              option.value === contentType
                ? "bg-violet-500 text-white shadow-glow"
                : "text-slate-300 hover:bg-violet-400/10 hover:text-white"
            }`}
            type="button"
            aria-pressed={option.value === contentType}
            onClick={() => selectContentType(option.value)}
          >
            {option.label}
          </button>
        ))}
      </div>

      <form
        className="relative z-20 mb-4 grid gap-3 rounded-2xl border border-white/10 bg-slate-900/70 p-4 shadow-xl backdrop-blur sm:grid-cols-2 lg:grid-cols-6"
        onSubmit={submitFilters}
      >
        <label className="sm:col-span-2 lg:col-span-2">
          <span className="sr-only">Search catalogue</span>
          <input
            className="filter-input"
            name="q"
            placeholder={`Search ${
              contentType === "ALL" ? "all titles" : contentDetails.resultLabel
            }`}
            value={filters.q}
            onChange={changeFilter}
          />
        </label>

        <div
          id="genre-tag-filter"
          className={`${mobileFiltersOpen ? "block" : "hidden"} sm:block`}
        >
          <GenreTagPicker
            filters={filters}
            genres={genres}
            tagOptions={tagOptions}
            tagQuery={tagQuery}
            tagsLoading={tagsLoading}
            dropdownOpen={genreDropdownOpen}
            dropdownRef={genreDropdownRef}
            onDropdownToggle={(isOpen) => {
              setGenreDropdownOpen(isOpen);
              if (!isOpen) setTagQuery("");
            }}
            onQueryChange={setTagQuery}
            onGenreToggle={toggleGenre}
            onTagToggle={toggleTag}
          />
        </div>

        {contentType === "ANIME" && (
          <label
            id="anime-type-filter"
            className={`${mobileFiltersOpen ? "block" : "hidden"} sm:block`}
          >
            <span className="sr-only">Anime type</span>
            <select
              className="filter-input !bg-slate-950"
              name="type"
              value={filters.type}
              onChange={changeFilter}
              onFocus={() => setAllTypesExplicitlySelected(true)}
              style={{ colorScheme: "dark" }}
            >
              <option className="bg-slate-950" value="">All types</option>
              <option className="bg-slate-950" value="TV">TV</option>
              <option className="bg-slate-950" value="MOVIE">Movie</option>
              <option className="bg-slate-950" value="OVA">OVA</option>
              <option className="bg-slate-950" value="ONA">ONA</option>
              <option className="bg-slate-950" value="SPECIAL">Special</option>
            </select>
          </label>
        )}

        {contentType === "ANIME" && (
          <label
            id="anime-status-filter"
            className={`${mobileFiltersOpen ? "block" : "hidden"} sm:block`}
          >
            <span className="sr-only">Airing status</span>
            <select
              className="filter-input !bg-slate-950"
              name="status"
              value={filters.status}
              onChange={changeFilter}
              style={{ colorScheme: "dark" }}
            >
              <option className="bg-slate-950" value="">All statuses</option>
              <option className="bg-slate-950" value="CURRENTLY_AIRING">
                Currently Airing
              </option>
              <option className="bg-slate-950" value="FINISHED_AIRING">
                Finished Airing
              </option>
              <option className="bg-slate-950" value="NOT_YET_AIRED">
                Not Yet Aired
              </option>
            </select>
          </label>
        )}

        {(contentType === "MANGA" || contentType === "MANHWA") && (
          <label
            id="print-status-filter"
            className={`${mobileFiltersOpen ? "block" : "hidden"} sm:block`}
          >
            <span className="sr-only">Publication status</span>
            <select
              className="filter-input !bg-slate-950"
              name="status"
              value={filters.status}
              onChange={changeFilter}
              style={{ colorScheme: "dark" }}
            >
              <option className="bg-slate-950" value="">All statuses</option>
              <option className="bg-slate-950" value="PUBLISHING">Publishing</option>
              <option className="bg-slate-950" value="FINISHED">Finished</option>
              <option className="bg-slate-950" value="ON_HIATUS">On hiatus</option>
              <option className="bg-slate-950" value="DISCONTINUED">Discontinued</option>
              <option className="bg-slate-950" value="NOT_YET_PUBLISHED">
                Not yet published
              </option>
            </select>
          </label>
        )}

        <div className="flex gap-2">
          <button
            className="flex-1 rounded-xl border border-white/15 px-3 py-3 text-sm font-semibold text-slate-200 transition hover:border-violet-400 hover:text-white sm:hidden"
            type="button"
            aria-controls={`genre-tag-filter${
              contentType === "ANIME"
                ? " anime-type-filter anime-status-filter"
                : contentType === "ALL"
                  ? ""
                  : " print-status-filter"
            } mobile-more-filters`}
            aria-expanded={mobileFiltersOpen}
            onClick={() => setMobileFiltersOpen((open) => !open)}
          >
            Filters
          </button>
          <button
            className="flex-1 rounded-xl bg-violet-500 px-4 py-3 text-sm font-bold text-white hover:bg-violet-400"
            type="submit"
          >
            Search
          </button>
        </div>

        <div
          id="mobile-more-filters"
          className={responsiveFilterPanelClasses(mobileFiltersOpen, moreFiltersOpen)}
        >
          {contentType === "ANIME" && (
            <label>
              <span className="sr-only">Season</span>
              <select
                className="filter-input !bg-slate-950"
                name="season"
                value={filters.season}
                onChange={changeFilter}
                style={{ colorScheme: "dark" }}
              >
                <option className="bg-slate-950" value="">All seasons</option>
                <option className="bg-slate-950" value="winter">Winter</option>
                <option className="bg-slate-950" value="spring">Spring</option>
                <option className="bg-slate-950" value="summer">Summer</option>
                <option className="bg-slate-950" value="fall">Fall</option>
              </select>
            </label>
          )}
          <label>
            <span className="sr-only">Minimum score</span>
            <input
              className="filter-input"
              name="min_score"
              inputMode="decimal"
              min="0"
              max="10"
              step="0.1"
              placeholder="Minimum score"
              value={filters.min_score}
              onChange={changeFilter}
            />
          </label>
          <label>
            <span className="sr-only">From year</span>
            <input
              className="filter-input"
              name="min_year"
              inputMode="numeric"
              placeholder="From year"
              value={filters.min_year}
              onChange={changeFilter}
            />
          </label>
          <label>
            <span className="sr-only">To year</span>
            <input
              className="filter-input"
              name="max_year"
              inputMode="numeric"
              placeholder="To year"
              value={filters.max_year}
              onChange={changeFilter}
            />
          </label>

          {contentType === "ANIME" && (
            <>
              <label>
                <span className="sr-only">Minimum episodes</span>
                <input
                  className="filter-input"
                  name="min_episodes"
                  inputMode="numeric"
                  min="1"
                  placeholder="Minimum episodes"
                  value={filters.min_episodes}
                  onChange={changeFilter}
                />
              </label>
              <label>
                <span className="sr-only">Maximum episodes</span>
                <input
                  className="filter-input"
                  name="max_episodes"
                  inputMode="numeric"
                  min="1"
                  placeholder="Maximum episodes"
                  value={filters.max_episodes}
                  onChange={changeFilter}
                />
              </label>
            </>
          )}

          {(contentType === "MANGA" || contentType === "MANHWA") && (
            <>
              <label>
                <span className="sr-only">Minimum chapters</span>
                <input
                  className="filter-input"
                  name="min_chapters"
                  inputMode="numeric"
                  min="1"
                  placeholder="Minimum chapters"
                  value={filters.min_chapters}
                  onChange={changeFilter}
                />
              </label>
              <label>
                <span className="sr-only">Minimum volumes</span>
                <input
                  className="filter-input"
                  name="min_volumes"
                  inputMode="numeric"
                  min="1"
                  placeholder="Minimum volumes"
                  value={filters.min_volumes}
                  onChange={changeFilter}
                />
              </label>
            </>
          )}
        </div>

        <div className="flex flex-wrap items-center justify-between gap-2 sm:col-span-2 lg:col-span-6">
          <button
            className="hidden rounded-lg border border-white/15 px-3 py-2 text-xs font-semibold text-slate-200 transition hover:border-violet-400 hover:text-white sm:inline-flex"
            type="button"
            aria-controls="mobile-more-filters"
            aria-expanded={moreFiltersOpen}
            onClick={() => setMoreFiltersOpen((open) => !open)}
          >
            {moreFiltersOpen ? "Hide extra filters" : "More filters"}
          </button>
          <button
            className="rounded-lg border border-white/15 px-3 py-2 text-xs font-semibold text-slate-200 transition hover:border-violet-400 hover:text-white disabled:cursor-not-allowed disabled:opacity-40"
            type="button"
            onClick={clearSelections}
            disabled={!hasSelections && viewMode === defaultViewMode && sort === DEFAULT_SORT}
          >
            Clear selections
          </button>
        </div>
      </form>

      <div className="mb-5 space-y-3">
        <div className="flex flex-wrap items-center gap-2" aria-label="Filter presets">
          <span className="mr-1 text-xs font-bold uppercase tracking-widest text-slate-500">
            Quick picks
          </span>
          {filterPresets.map((preset) => (
            <button
              key={preset.id}
              className={`rounded-full border px-3 py-1.5 text-xs font-semibold transition ${
                activePreset === preset.id
                  ? "border-violet-400 bg-violet-500 text-white"
                  : "border-white/10 bg-slate-900/70 text-slate-300 hover:border-violet-400"
              }`}
              type="button"
              aria-pressed={activePreset === preset.id}
              onClick={() => applyPreset(preset)}
            >
              {preset.label}
            </button>
          ))}
        </div>

        {chips.length > 0 && (
          <div className="flex flex-wrap items-center gap-2" aria-label="Active filters">
            {chips.map((chip) => (
              <button
                key={`${chip.key}:${chip.value}`}
                className="inline-flex items-center gap-2 rounded-full border border-violet-400/30 bg-violet-400/10 px-3 py-1.5 text-xs font-semibold text-violet-100 transition hover:border-violet-300 hover:bg-violet-400/20"
                type="button"
                onClick={() => removeChip(chip)}
                aria-label={`Remove ${chip.label} filter`}
              >
                {chip.label}
                <span aria-hidden="true">×</span>
              </button>
            ))}
            <button
              className="px-2 py-1.5 text-xs font-bold text-slate-400 underline-offset-4 hover:text-white hover:underline"
              type="button"
              onClick={clearSelections}
            >
              Clear all
            </button>
          </div>
        )}
      </div>

      {error && (
        <div className="mb-6 rounded-xl border border-rose-400/40 bg-rose-950/60 p-4 text-rose-100">
          {error}
        </div>
      )}

      {showHomepageSections && (
        <section className="mb-12" aria-labelledby="popular-this-season">
          <h2
            id="popular-this-season"
            className="mb-5 text-3xl font-black tracking-tight text-white sm:text-4xl"
          >
            POPULAR THIS SEASON
          </h2>
          {seasonalLoading ? (
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
              {Array.from({ length: 6 }, (_, index) => (
                <div key={index} className="aspect-[2/3] animate-pulse rounded-2xl bg-slate-800" />
              ))}
            </div>
          ) : seasonalAnime.length > 0 ? (
            <div className="relative">
              <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
                {seasonalAnime.map((entry) => (
                  <CatalogueCard
                    key={`ANIME:${entry.mal_id ?? entry.id}`}
                    item={{ ...entry, content_type: "ANIME" }}
                    onSelect={openDetail}
                  />
                ))}
              </div>
              <button
                className="absolute -left-3 top-1/2 z-10 -translate-y-1/2 rounded-full border border-white/15 bg-slate-900/90 px-3 py-4 text-2xl font-bold text-white shadow-lg transition hover:border-violet-400 hover:bg-violet-500 disabled:cursor-not-allowed disabled:opacity-30"
                type="button"
                aria-label="Previous popular seasonal anime"
                disabled={seasonalPagination.page === 1}
                onClick={() => loadSeasonalAnime(seasonalPagination.page - 1)}
              >
                &lsaquo;
              </button>
              <button
                className="absolute -right-3 top-1/2 z-10 -translate-y-1/2 rounded-full border border-white/15 bg-slate-900/90 px-3 py-4 text-2xl font-bold text-white shadow-lg transition hover:border-violet-400 hover:bg-violet-500 disabled:cursor-not-allowed disabled:opacity-30"
                type="button"
                aria-label="Next popular seasonal anime"
                disabled={seasonalPagination.page === seasonalPagination.pages}
                onClick={() => loadSeasonalAnime(seasonalPagination.page + 1)}
              >
                &rsaquo;
              </button>
            </div>
          ) : (
            <p className="rounded-2xl border border-dashed border-slate-700 p-5 text-sm text-slate-400">
              Seasonal anime are still being refreshed. Check back shortly.
            </p>
          )}
        </section>
      )}

      <section aria-label={`${contentDetails.label} results`}>
        <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
          <div>
            {showHomepageSections && (
              <h2
                id="top-rated"
                className="text-3xl font-black tracking-tight text-white sm:text-4xl"
              >
                TOP RATED
              </h2>
            )}
            {!loading && !error && (
              <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-slate-400">
                <span>
                  {pagination.total.toLocaleString()} {contentDetails.resultLabel} found
                </span>
                {freshness && (
                  <span title={new Date(updatedAt).toLocaleString()}>
                    {freshness}
                  </span>
                )}
              </div>
            )}
          </div>
          {viewMode !== "random" && (
            <label className="flex items-center gap-2 text-sm text-slate-400">
              <span>Sort</span>
              <select
                className="rounded-lg border border-white/10 bg-slate-950 px-3 py-2 text-sm font-semibold text-white outline-none focus:border-violet-400"
                value={sort}
                onChange={changeSort}
                aria-label="Sort catalogue"
                style={{ colorScheme: "dark" }}
              >
                {sortOptionsFor(contentType).map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>

        {loading ? (
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
            {Array.from({ length: 12 }, (_, index) => (
              <div key={index} className="aspect-[2/3] animate-pulse rounded-2xl bg-slate-800" />
            ))}
          </div>
        ) : items.length > 0 ? (
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6">
            {items.map((entry) => (
              <CatalogueCard
                key={`${itemContentType(entry)}:${entry.mal_id ?? entry.id}`}
                item={entry}
                onSelect={openDetail}
                showContentBadge={contentType === "ALL"}
              />
            ))}
          </div>
        ) : !error && (
          <div className="rounded-2xl border border-dashed border-slate-600 p-12 text-center text-slate-300">
            No {contentDetails.resultLabel} match those filters. Try widening your search.
          </div>
        )}
      </section>

      {!loading && pagination.pages > 1 && viewMode !== "random" && (
        <nav
          className="mt-10 flex flex-col items-center gap-4"
          aria-label="Pagination"
        >
          <p className="text-sm font-semibold text-slate-300">
            Page {pagination.page.toLocaleString()} of {pagination.pages.toLocaleString()}
          </p>
          <div className="flex flex-wrap items-center justify-center gap-2">
            <button
              className="rounded-lg border border-white/15 px-3 py-2 font-semibold transition hover:border-violet-400 disabled:cursor-not-allowed disabled:opacity-40"
              disabled={pagination.page === 1}
              onClick={() => goToPage(1)}
              type="button"
              aria-label="First page"
            >
              &lt;&lt;
            </button>
            {visiblePageNumbers(pagination.page, pagination.pages).map((pageNumber) => (
              <button
                key={pageNumber}
                className={`min-w-10 rounded-lg border px-3 py-2 font-semibold transition ${
                  pageNumber === pagination.page
                    ? "border-violet-400 bg-violet-500 text-white"
                    : "border-white/15 text-slate-200 hover:border-violet-400"
                }`}
                onClick={() => goToPage(pageNumber)}
                type="button"
                aria-current={pageNumber === pagination.page ? "page" : undefined}
                aria-label={`Page ${pageNumber}`}
              >
                {pageNumber}
              </button>
            ))}
            <button
              className="rounded-lg border border-white/15 px-3 py-2 font-semibold transition hover:border-violet-400 disabled:cursor-not-allowed disabled:opacity-40"
              disabled={pagination.page === pagination.pages}
              onClick={() => goToPage(pagination.pages)}
              type="button"
              aria-label="Last page"
            >
              &gt;&gt;
            </button>
          </div>
          <form
            className="flex flex-wrap items-start justify-center gap-2"
            onSubmit={submitPageJump}
          >
            <label className="flex items-center gap-2 text-sm text-slate-400">
              <span>Jump to page</span>
              <input
                className="w-24 rounded-lg border border-white/15 bg-slate-950 px-3 py-2 text-white outline-none focus:border-violet-400"
                type="number"
                min="1"
                max={pagination.pages}
                inputMode="numeric"
                value={jumpPage}
                onChange={(event) => {
                  setJumpPage(event.target.value);
                  setPageError("");
                }}
                aria-describedby={pageError ? "page-jump-error" : undefined}
              />
            </label>
            <button
              className="rounded-lg bg-violet-500 px-4 py-2 font-bold text-white transition hover:bg-violet-400"
              type="submit"
            >
              Go
            </button>
            {pageError && (
              <p
                id="page-jump-error"
                className="basis-full text-center text-xs text-rose-300"
                role="alert"
              >
                {pageError}
              </p>
            )}
          </form>
        </nav>
      )}

      <DetailModal item={selected} loading={detailLoading} onClose={closeDetail} />
    </main>
  );
}
