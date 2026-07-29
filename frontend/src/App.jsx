import { useCallback, useEffect, useRef, useState } from "react";
import {
  CONTENT_TYPES,
  TOP_RATED_FILTERS,
  contentTypeDetails,
  filtersFor,
  filtersMatch,
  itemContentType,
  itemMetadata,
  queryString,
  visiblePageNumbers,
} from "./catalogue.js";

function Score({ value }) {
  const numericValue = value === null || value === undefined || value === ""
    ? Number.NaN
    : Number(value);
  const label = Number.isFinite(numericValue) ? numericValue.toFixed(2) : "—";
  return (
    <span className="rounded-full bg-amber-300/15 px-2.5 py-1 text-sm font-bold text-amber-300">
      ★ {label}
    </span>
  );
}

function CatalogueCard({ item, onSelect }) {
  const metadata = itemMetadata(item).join(" · ");

  return (
    <button
      className="group flex h-full flex-col overflow-hidden rounded-2xl border border-white/10 bg-slate-900/80 text-left shadow-lg transition hover:-translate-y-1 hover:border-violet-400/60 hover:shadow-glow focus:outline-none focus:ring-2 focus:ring-violet-400"
      onClick={() => onSelect(item)}
      type="button"
    >
      <div className="relative aspect-[2/3] shrink-0 overflow-hidden bg-slate-800">
        <img
          className="block h-full w-full object-cover object-center transition duration-300 group-hover:scale-105"
          src={item.image_url}
          alt={`${item.title} cover`}
          loading="lazy"
        />
        <div className="absolute bottom-3 left-3"><Score value={item.score} /></div>
      </div>
      <div className="flex flex-1 flex-col space-y-2 p-4">
        <h2 className="line-clamp-2 min-h-12 text-base font-bold text-white">{item.title}</h2>
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
            {loading && <p className="text-sm text-violet-200" role="status">Loading full details…</p>}
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

export default function App() {
  const [contentType, setContentType] = useState("ANIME");
  const [filters, setFilters] = useState(() => filtersFor("ANIME"));
  const [appliedFilters, setAppliedFilters] = useState(TOP_RATED_FILTERS);
  const [genres, setGenres] = useState([]);
  const [tagOptions, setTagOptions] = useState([]);
  const [tagQuery, setTagQuery] = useState("");
  const [tagsLoading, setTagsLoading] = useState(false);
  const [genreDropdownOpen, setGenreDropdownOpen] = useState(false);
  const [items, setItems] = useState([]);
  const [seasonalAnime, setSeasonalAnime] = useState([]);
  const [pagination, setPagination] = useState({ page: 1, pages: 1, total: 0 });
  const [seasonalPagination, setSeasonalPagination] = useState({
    page: 1,
    pages: 1,
    total: 0,
  });
  const [loading, setLoading] = useState(true);
  const [seasonalLoading, setSeasonalLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [viewMode, setViewMode] = useState("home");
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
  ) => {
    const requestId = ++catalogueRequestRef.current;
    setLoading(true);
    setError("");
    try {
      const response = await fetch(
        `/api/v1/catalogue?${queryString(activeFilters, page, activeContentType)}`,
      );
      const body = await response.json();
      if (!response.ok) {
        const label = contentTypeDetails(activeContentType).resultLabel;
        throw new Error(body.error?.message || `Could not load ${label}.`);
      }
      if (requestId !== catalogueRequestRef.current) return;
      setItems(body.items ?? []);
      setPagination(body.pagination ?? { page: 1, pages: 1, total: 0 });
    } catch (requestError) {
      if (requestId !== catalogueRequestRef.current) return;
      setItems([]);
      setPagination({ page: 1, pages: 1, total: 0 });
      setError(requestError.message);
    } finally {
      if (requestId === catalogueRequestRef.current) setLoading(false);
    }
  }, []);

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
    loadCatalogue(1, TOP_RATED_FILTERS, "ANIME");
    loadSeasonalAnime();
  }, [loadCatalogue, loadSeasonalAnime]);

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

  const defaultFilters = filtersFor(contentType);
  const hasSelections = !filtersMatch(filters, defaultFilters);
  const defaultViewMode = contentType === "ANIME" ? "home" : "results";
  const showHomepageSections = contentType === "ANIME" && viewMode === "home";
  const contentDetails = contentTypeDetails(contentType);
  const matchingGenres = genres.filter((genre) => (
    genre.toLowerCase().includes(tagQuery.trim().toLowerCase())
  ));

  const submitFilters = (event) => {
    event.preventDefault();
    const submittedFilters = {
      ...filters,
      genre: [...filters.genre],
      tag: [...filters.tag],
    };
    const returnsHome = contentType === "ANIME" && !hasSelections;
    const requestFilters = returnsHome ? TOP_RATED_FILTERS : submittedFilters;
    setAppliedFilters(requestFilters);
    setViewMode(returnsHome ? "home" : "results");
    loadCatalogue(1, requestFilters, contentType);
  };

  const selectContentType = (nextContentType) => {
    if (nextContentType === contentType) return;

    const nextFilters = filtersFor(nextContentType);
    ++detailRequestRef.current;
    setContentType(nextContentType);
    setFilters(nextFilters);
    const nextAppliedFilters = nextContentType === "ANIME"
      ? TOP_RATED_FILTERS
      : nextFilters;
    setAppliedFilters(nextAppliedFilters);
    setSelected(null);
    setDetailLoading(false);
    setTagQuery("");
    setTagOptions([]);
    setTagsLoading(false);
    ++tagRequestRef.current;
    setGenreDropdownOpen(false);
    genreDropdownRef.current?.removeAttribute("open");
    setViewMode(nextContentType === "ANIME" ? "home" : "results");
    loadCatalogue(1, nextAppliedFilters, nextContentType);
  };

  const showRandom = async () => {
    const requestId = ++catalogueRequestRef.current;
    setViewMode("random");
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams({ content_type: contentType, limit: "6" });
      const response = await fetch(`/api/v1/catalogue/random?${params}`);
      const body = await response.json();
      if (!response.ok) {
        throw new Error(body.error?.message || `Could not load random ${contentDetails.resultLabel}.`);
      }
      if (requestId !== catalogueRequestRef.current) return;
      const randomItems = body.items ?? [];
      setItems(randomItems);
      setPagination({ page: 1, pages: 1, total: randomItems.length });
    } catch (requestError) {
      if (requestId !== catalogueRequestRef.current) return;
      setItems([]);
      setPagination({ page: 1, pages: 1, total: 0 });
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
    setFilters((current) => ({ ...current, [event.target.name]: event.target.value }));
  };

  const toggleGenre = (genre) => {
    setFilters((current) => ({
      ...current,
      genre: current.genre.includes(genre)
        ? current.genre.filter((selectedGenre) => selectedGenre !== genre)
        : [...current.genre, genre],
    }));
  };

  const toggleTag = (tag) => {
    setFilters((current) => ({
      ...current,
      tag: current.tag.includes(tag)
        ? current.tag.filter((selectedTag) => selectedTag !== tag)
        : [...current.tag, tag],
    }));
  };

  const clearSelections = () => {
    const clearedFilters = filtersFor(contentType);
    const clearedAppliedFilters = contentType === "ANIME"
      ? TOP_RATED_FILTERS
      : clearedFilters;
    setFilters(clearedFilters);
    setAppliedFilters(clearedAppliedFilters);
    setViewMode(defaultViewMode);
    loadCatalogue(1, clearedAppliedFilters, contentType);
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
          Randomize {contentType === "ALL" ? "all" : contentDetails.label}
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
        className="relative z-20 mb-8 grid gap-3 rounded-2xl border border-white/10 bg-slate-900/70 p-4 shadow-xl backdrop-blur sm:grid-cols-2 lg:grid-cols-5"
        onSubmit={submitFilters}
      >
        <input
          className="filter-input sm:col-span-2"
          name="q"
          placeholder={`Search ${contentType === "ALL" ? "all titles" : contentDetails.resultLabel}`}
          value={filters.q}
          onChange={changeFilter}
        />
        <div className="relative">
          <details
            ref={genreDropdownRef}
            className="group"
            onToggle={(event) => {
              const isOpen = event.currentTarget.open;
              setGenreDropdownOpen(isOpen);
              if (!isOpen) setTagQuery("");
            }}
          >
            <summary className="filter-input flex cursor-pointer list-none items-center justify-between marker:hidden">
              {genreDropdownOpen ? (
                <input
                  className="min-w-0 flex-1 bg-transparent text-sm text-white outline-none placeholder:text-slate-400"
                  value={tagQuery}
                  onChange={(event) => setTagQuery(event.target.value)}
                  onClick={(event) => event.stopPropagation()}
                  placeholder="Search genres and tags"
                  aria-label="Search genres and tags"
                  autoFocus
                />
              ) : (
                <span>
                  {filters.genre.length + filters.tag.length
                    ? `${filters.genre.length + filters.tag.length} selected`
                    : "All genres + tags"}
                </span>
              )}
              <span className="text-violet-300 transition group-open:rotate-180">⌄</span>
            </summary>
            <div className="absolute z-20 mt-2 max-h-64 w-full overflow-y-auto rounded-xl border border-white/10 bg-slate-950 p-1 shadow-2xl">
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
                  onClick={() => toggleGenre(genre)}
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
                  onClick={() => toggleTag(tag)}
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

        {contentType === "ANIME" && (
          <>
            <select
              className="filter-input !bg-slate-950"
              name="type"
              value={filters.type}
              onChange={changeFilter}
              style={{ colorScheme: "dark" }}
            >
              <option className="bg-slate-950" value="">All types</option>
              <option className="bg-slate-950" value="TV">TV</option>
              <option className="bg-slate-950" value="MOVIE">Movie</option>
              <option className="bg-slate-950" value="OVA">OVA</option>
              <option className="bg-slate-950" value="ONA">ONA</option>
              <option className="bg-slate-950" value="SPECIAL">Special</option>
            </select>
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
          </>
        )}

        {(contentType === "MANGA" || contentType === "MANHWA") && (
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
            <option className="bg-slate-950" value="NOT_YET_PUBLISHED">Not yet published</option>
          </select>
        )}

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
        <input
          className="filter-input"
          name="min_year"
          inputMode="numeric"
          placeholder="From year"
          value={filters.min_year}
          onChange={changeFilter}
        />
        <input
          className="filter-input"
          name="max_year"
          inputMode="numeric"
          placeholder="To year"
          value={filters.max_year}
          onChange={changeFilter}
        />

        {contentType === "ANIME" && (
          <input
            className="filter-input"
            name="min_episodes"
            inputMode="numeric"
            min="1"
            placeholder="Minimum episodes"
            value={filters.min_episodes}
            onChange={changeFilter}
          />
        )}

        {(contentType === "MANGA" || contentType === "MANHWA") && (
          <>
            <input
              className="filter-input"
              name="min_chapters"
              inputMode="numeric"
              min="1"
              placeholder="Minimum chapters"
              value={filters.min_chapters}
              onChange={changeFilter}
            />
            <input
              className="filter-input"
              name="min_volumes"
              inputMode="numeric"
              min="1"
              placeholder="Minimum volumes"
              value={filters.min_volumes}
              onChange={changeFilter}
            />
          </>
        )}

        <div className="flex justify-end gap-2 sm:col-span-2 lg:col-span-5">
          <button
            className="rounded-xl border border-white/15 px-3 py-2 text-xs font-semibold text-slate-200 transition hover:border-violet-400 hover:text-white disabled:cursor-not-allowed disabled:opacity-40"
            type="button"
            onClick={clearSelections}
            disabled={!hasSelections && viewMode === defaultViewMode}
          >
            Clear selections
          </button>
          <button
            className="rounded-xl bg-violet-500 px-3 py-2 text-sm font-bold text-white hover:bg-violet-400"
            type="submit"
          >
            Search
          </button>
        </div>
      </form>

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
        {showHomepageSections && (
          <div className="mb-5 flex flex-wrap items-end justify-between gap-2">
            <h2
              id="top-rated"
              className="text-3xl font-black tracking-tight text-white sm:text-4xl"
            >
              TOP RATED
            </h2>
            {!loading && !error && (
              <p className="text-sm text-slate-400">
                {pagination.total.toLocaleString()} anime found
              </p>
            )}
          </div>
        )}
        {!showHomepageSections && !loading && !error && (
          <p className="mb-5 text-sm text-slate-400">
            {pagination.total.toLocaleString()} {contentDetails.resultLabel} found
          </p>
        )}
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
              />
            ))}
          </div>
        ) : !error && (
          <div className="rounded-2xl border border-dashed border-slate-600 p-12 text-center text-slate-300">
            No {contentDetails.resultLabel} match those filters. Try widening your search.
          </div>
        )}
      </section>

      {!loading && pagination.pages > 1 && (
        <nav className="mt-10 flex flex-wrap items-center justify-center gap-2" aria-label="Pagination">
          <button
            className="rounded-lg border border-white/15 px-3 py-2 font-semibold transition hover:border-violet-400 disabled:cursor-not-allowed disabled:opacity-40"
            disabled={pagination.page === 1}
            onClick={() => loadCatalogue(1, appliedFilters, contentType)}
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
              onClick={() => loadCatalogue(pageNumber, appliedFilters, contentType)}
              type="button"
              aria-current={pageNumber === pagination.page ? "page" : undefined}
            >
              {pageNumber}
            </button>
          ))}
          <button
            className="rounded-lg border border-white/15 px-3 py-2 font-semibold transition hover:border-violet-400 disabled:cursor-not-allowed disabled:opacity-40"
            disabled={pagination.page === pagination.pages}
            onClick={() => loadCatalogue(pagination.pages, appliedFilters, contentType)}
            type="button"
            aria-label="Last page"
          >
            &gt;&gt;
          </button>
        </nav>
      )}

      <DetailModal item={selected} loading={detailLoading} onClose={closeDetail} />
    </main>
  );
}
