import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
} from "react";
import {
  CONTENT_TYPES,
  DEFAULT_SORT,
  TOP_RATED_FILTERS,
  activeFilterChips,
  catalogueStateFromSearch,
  catalogueUrlSearch,
  contentTypeDetails,
  discreteRangeValues,
  filtersFor,
  filtersFromPreset,
  filtersMatch,
  filtersWithoutChip,
  formatFreshness,
  itemContentType,
  itemMetadata,
  namedValues,
  nearestRangeIndex,
  presetsFor,
  queryString,
  randomQueryString,
  rangeSelectionLabel,
  responsiveFilterPanelClasses,
  scoreLabel,
  sortOptionsFor,
  streamingServiceEntries,
  usesTopRatedAnimeHomepage,
  validatedPage,
  visiblePageNumbers,
} from "./catalogue.js";

const DEFAULT_FILTER_RANGES = {
  year: { min: 1900, max: new Date().getFullYear() + 2, step: 1 },
  score: { min: 0, max: 10, step: 0.1 },
  episodes: { min: 1, max: 1000, step: 1 },
  chapters: { min: 1, max: 1000, step: 1 },
  volumes: { min: 1, max: 100, step: 1 },
};

const FILTER_LAYOUTS = {
  ANIME: {
    grid: "sm:grid-cols-2 lg:grid-cols-5",
    panelSpan: "lg:col-span-5",
    panelGrid: "lg:grid-cols-5",
  },
  MANGA: {
    grid: "sm:grid-cols-2 lg:grid-cols-5",
    panelSpan: "lg:col-span-5",
    panelGrid: "lg:grid-cols-5",
  },
  MANHWA: {
    grid: "sm:grid-cols-2 lg:grid-cols-5",
    panelSpan: "lg:col-span-5",
    panelGrid: "lg:grid-cols-5",
  },
  ALL: {
    grid: "sm:grid-cols-2 lg:grid-cols-5",
    panelSpan: "lg:col-span-5",
    panelGrid: "lg:grid-cols-5",
  },
};

function normalizedFilterRanges(payload) {
  const source = payload?.ranges ?? payload ?? {};
  return Object.fromEntries(
    Object.entries(DEFAULT_FILTER_RANGES).map(([key, fallback]) => {
      if (key === "score") return [key, fallback];
      const values = source[key] ?? {};
      const minimum = Number(
        values.min ?? values.minimum ?? source[`min_${key}`],
      );
      const maximum = Number(
        values.max ?? values.maximum ?? source[`max_${key}`],
      );
      const min = Number.isFinite(minimum) ? minimum : fallback.min;
      const maxCandidate = Number.isFinite(maximum) ? maximum : fallback.max;
      return [
        key,
        {
          min,
          max: Math.max(min, maxCandidate),
          step: fallback.step,
        },
      ];
    }),
  );
}

function copiedFilters(filters) {
  return Object.fromEntries(
    Object.entries(filters).map(([key, value]) => [
      key,
      Array.isArray(value) ? [...value] : value,
    ]),
  );
}

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
  const visibleGenres = (item.genres ?? []).slice(0, 4);

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
        <div className="mt-auto flex h-14 content-start flex-wrap gap-1.5 overflow-hidden">
          {visibleGenres.map((genre) => (
            <span
              key={genre}
              className="h-7 shrink-0 rounded-full bg-violet-400/10 px-2 py-1 text-xs text-violet-200"
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
  const studios = contentType === "ANIME" ? namedValues(item.studios) : [];
  const authors = contentType === "ANIME"
    ? []
    : (item.authors ?? [])
      .map((entry) => ({
        name: String(entry?.name ?? "").trim(),
        role: String(entry?.role ?? "").trim(),
      }))
      .filter(({ name }) => name);
  const streamingServices = contentType === "ANIME"
    ? streamingServiceEntries(item.streaming_services ?? item.streaming)
    : [];

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
            {studios.length > 0 && (
              <p className="text-sm leading-6 text-slate-300">
                <span className="font-semibold text-violet-200">
                  {studios.length === 1 ? "Studio:" : "Studios:"}
                </span>{" "}
                {studios.join(", ")}
              </p>
            )}
            {authors.length > 0 && (
              <p className="text-sm leading-6 text-slate-300">
                <span className="font-semibold text-violet-200">
                  {authors.length === 1 ? "Author:" : "Authors:"}
                </span>{" "}
                {authors.map(({ name, role }) => (
                  role ? `${name} (${role})` : name
                )).join(", ")}
              </p>
            )}
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
            {streamingServices.length > 0 && (
              <section>
                <h3 className="text-sm font-semibold uppercase tracking-widest text-violet-300">
                  Streaming services
                </h3>
                <div className="mt-2 flex flex-wrap gap-2">
                  {streamingServices.map(({ name, url }) => (
                    url ? (
                      <a
                        key={name}
                        className="rounded-full border border-violet-400/30 bg-violet-400/10 px-3 py-1.5 text-sm font-semibold text-violet-100 transition hover:border-violet-300 hover:bg-violet-400/20"
                        href={url}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        {name} ↗
                      </a>
                    ) : (
                      <span
                        key={name}
                        className="rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-sm text-slate-300"
                      >
                        {name}
                      </span>
                    )
                  ))}
                </div>
                <p className="mt-2 text-xs leading-5 text-slate-500">
                  Availability varies by region and may change.
                </p>
              </section>
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
                rel="noopener noreferrer"
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
                ? `Genres & Tags (${filters.genre.length + filters.tag.length})`
                : "Genres & Tags"}
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
        </div>
      </details>
    </div>
  );
}

export function SearchableMultiSelect({
  label,
  selected,
  options,
  query,
  loading,
  open,
  dropdownRef,
  onOpenChange,
  onQueryChange,
  onToggle,
}) {
  const listId = useId();
  const statusId = useId();
  const triggerRef = useRef(null);
  const restoreFocusRef = useRef(false);
  const wasOpenRef = useRef(open);
  const [activeIndex, setActiveIndex] = useState(0);
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const matchingOptions = options.filter((option) => (
    option.toLocaleLowerCase().includes(normalizedQuery)
  ));
  const safeActiveIndex = Math.min(
    activeIndex,
    Math.max(0, matchingOptions.length - 1),
  );
  const hasNavigableOptions = !loading && matchingOptions.length > 0;
  const activeOptionId = matchingOptions.length > 0
    ? `${listId}-option-${safeActiveIndex}`
    : undefined;

  useEffect(() => {
    if (!open) return;
    setActiveIndex(0);
  }, [open, query]);

  useEffect(() => {
    if (wasOpenRef.current && !open && restoreFocusRef.current) {
      window.setTimeout(() => triggerRef.current?.focus(), 0);
    }
    if (!open) restoreFocusRef.current = false;
    wasOpenRef.current = open;
  }, [open]);

  const closeAndRestoreFocus = () => {
    restoreFocusRef.current = true;
    onOpenChange(false);
  };

  return (
    <div className="relative" ref={dropdownRef}>
      {open ? (
        <div className="filter-input flex items-center gap-2">
          <input
            className="min-w-0 flex-1 bg-transparent text-sm text-white outline-none placeholder:text-slate-400"
            value={query}
            onChange={(event) => onQueryChange(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "ArrowDown" && hasNavigableOptions) {
                event.preventDefault();
                setActiveIndex((current) => (
                  (current + 1) % matchingOptions.length
                ));
              } else if (event.key === "ArrowUp" && hasNavigableOptions) {
                event.preventDefault();
                setActiveIndex((current) => (
                  (current - 1 + matchingOptions.length) % matchingOptions.length
                ));
              } else if (event.key === "Home" && hasNavigableOptions) {
                event.preventDefault();
                setActiveIndex(0);
              } else if (event.key === "End" && hasNavigableOptions) {
                event.preventDefault();
                setActiveIndex(matchingOptions.length - 1);
              } else if (event.key === "Enter") {
                event.preventDefault();
                if (hasNavigableOptions) {
                  onToggle(
                    matchingOptions[safeActiveIndex],
                  );
                }
              } else if (event.key === "Escape") {
                event.preventDefault();
                event.stopPropagation();
                closeAndRestoreFocus();
              }
            }}
            placeholder={`Search ${label.toLocaleLowerCase()}`}
            aria-label={`Search ${label.toLocaleLowerCase()}`}
            role="combobox"
            aria-expanded="true"
            aria-controls={listId}
            aria-autocomplete="list"
            aria-activedescendant={!loading ? activeOptionId : undefined}
            aria-describedby={statusId}
            autoFocus
          />
          <button
            className="shrink-0 text-violet-300"
            type="button"
            aria-label={`Close ${label.toLocaleLowerCase()}`}
            onClick={closeAndRestoreFocus}
          >
            ⌃
          </button>
        </div>
      ) : (
        <button
          className="filter-input flex items-center justify-between text-left"
          ref={triggerRef}
          type="button"
          aria-haspopup="listbox"
          aria-expanded="false"
          aria-controls={listId}
          onClick={() => {
            restoreFocusRef.current = false;
            onOpenChange(true);
          }}
        >
          <span>{selected.length ? `${label} (${selected.length})` : label}</span>
          <span className="text-violet-300" aria-hidden="true">⌄</span>
        </button>
      )}
      {open && (
        <p id={statusId} className="sr-only" aria-live="polite">
          {loading
            ? "Loading options"
            : `${matchingOptions.length} option${
              matchingOptions.length === 1 ? "" : "s"
            } available`}
        </p>
      )}
      {open && (
        <div
          id={listId}
          className="absolute z-40 mt-2 max-h-72 w-full min-w-64 overflow-y-auto rounded-xl border border-white/10 bg-slate-950 p-1 shadow-2xl"
          role="listbox"
          aria-label={label}
          aria-multiselectable="true"
        >
          {loading ? (
            <p className="px-3 py-2 text-sm text-slate-400" role="status">
              Loading options…
            </p>
          ) : matchingOptions.length > 0 ? matchingOptions.map((option, index) => (
            <button
              key={option}
              id={`${listId}-option-${index}`}
              className={`block w-full rounded-lg px-3 py-2 text-left text-sm transition ${
                selected.includes(option)
                  ? "bg-violet-500 text-white"
                  : "text-slate-300 hover:bg-violet-400/10"
              } ${index === safeActiveIndex ? "ring-1 ring-inset ring-violet-300" : ""}`}
              type="button"
              role="option"
              aria-selected={selected.includes(option)}
              tabIndex={-1}
              onPointerMove={() => setActiveIndex(index)}
              onClick={() => onToggle(option)}
            >
              {option}
            </button>
          )) : (
            <p className="px-3 py-2 text-sm text-slate-400">
              No matching options.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

export function DualRangeSlider({
  label,
  minName,
  maxName,
  minValue,
  maxValue,
  bounds,
  scale = "linear",
  onValueChange,
}) {
  const outputId = useId();
  const minimumInputRef = useRef(null);
  const maximumInputRef = useRef(null);
  const activePointerHandleRef = useRef(null);
  const parsedMinimum = Number(minValue);
  const parsedMaximum = Number(maxValue);
  const selectedMinimum = minValue !== "" && Number.isFinite(parsedMinimum)
    ? parsedMinimum
    : bounds.min;
  const selectedMaximum = maxValue !== "" && Number.isFinite(parsedMaximum)
    ? parsedMaximum
    : bounds.max;
  const floor = Math.min(
    bounds.min,
    selectedMinimum,
    selectedMaximum,
  );
  const ceiling = Math.max(
    bounds.max,
    selectedMinimum,
    selectedMaximum,
  );
  const scaleValues = discreteRangeValues(
    floor,
    ceiling,
    scale,
    [selectedMinimum, selectedMaximum],
  );
  const selectedMinimumIndex = nearestRangeIndex(scaleValues, selectedMinimum);
  const selectedMaximumIndex = nearestRangeIndex(scaleValues, selectedMaximum);
  const safeMinimumIndex = Math.min(
    selectedMinimumIndex,
    selectedMaximumIndex,
  );
  const safeMaximumIndex = Math.max(
    selectedMinimumIndex,
    selectedMaximumIndex,
  );
  const safeMinimum = scaleValues[safeMinimumIndex];
  const safeMaximum = scaleValues[safeMaximumIndex];
  const scaleMaximumIndex = Math.max(0, scaleValues.length - 1);
  const span = Math.max(1, scaleMaximumIndex);
  const left = (safeMinimumIndex / span) * 100;
  const right = (safeMaximumIndex / span) * 100;
  const inactive = minValue === "" && maxValue === "";

  const updateHandle = (handle, index) => {
    const safeIndex = Math.max(
      0,
      Math.min(scaleMaximumIndex, Math.round(index)),
    );
    if (handle === "minimum") {
      const clampedIndex = Math.min(safeIndex, safeMaximumIndex);
      onValueChange(minName, String(scaleValues[clampedIndex]));
    } else {
      const clampedIndex = Math.max(safeIndex, safeMinimumIndex);
      onValueChange(maxName, String(scaleValues[clampedIndex]));
    }
  };

  const indexFromPointer = (event) => {
    const boundsRect = event.currentTarget.getBoundingClientRect();
    if (boundsRect.width <= 0) return safeMinimumIndex;
    const position = Math.max(
      0,
      Math.min(1, (event.clientX - boundsRect.left) / boundsRect.width),
    );
    return Math.round(position * scaleMaximumIndex);
  };

  const pointerDown = (event) => {
    event.preventDefault();
    const pointerIndex = indexFromPointer(event);
    let handle;
    if (safeMinimumIndex === safeMaximumIndex) {
      handle = pointerIndex >= safeMaximumIndex ? "maximum" : "minimum";
    } else {
      const minimumDistance = Math.abs(pointerIndex - safeMinimumIndex);
      const maximumDistance = Math.abs(pointerIndex - safeMaximumIndex);
      handle = minimumDistance < maximumDistance ? "minimum" : "maximum";
    }
    activePointerHandleRef.current = handle;
    event.currentTarget.setPointerCapture?.(event.pointerId);
    (handle === "minimum" ? minimumInputRef : maximumInputRef).current?.focus();
    updateHandle(handle, pointerIndex);
  };

  const pointerMove = (event) => {
    if (!activePointerHandleRef.current) return;
    event.preventDefault();
    updateHandle(activePointerHandleRef.current, indexFromPointer(event));
  };

  const endPointer = (event) => {
    if (!activePointerHandleRef.current) return;
    event.currentTarget.releasePointerCapture?.(event.pointerId);
    activePointerHandleRef.current = null;
  };

  return (
    <fieldset className="range-filter rounded-xl border border-white/10 bg-slate-950 px-3 py-2.5">
      <legend className="sr-only">{label}</legend>
      <div className="flex items-center justify-between gap-3">
        <span className="text-sm font-semibold text-slate-200">{label}</span>
        <div className="flex items-center gap-2">
          <output
            id={outputId}
            className="text-xs font-semibold tabular-nums text-violet-200"
          >
            {rangeSelectionLabel(minValue, maxValue)}
          </output>
          <button
            className="text-xs font-semibold text-slate-400 underline-offset-2 hover:text-white hover:underline disabled:cursor-not-allowed disabled:opacity-40"
            type="button"
            disabled={inactive}
            onClick={() => {
              onValueChange(minName, "");
              onValueChange(maxName, "");
            }}
            aria-label={`Clear ${label.toLocaleLowerCase()} range`}
          >
            Clear
          </button>
        </div>
      </div>
      <div
        className="dual-range mt-2"
        data-testid={`${minName}-${maxName}-track`}
        onPointerDown={pointerDown}
        onPointerMove={pointerMove}
        onPointerUp={endPointer}
        onPointerCancel={endPointer}
      >
        <div className="dual-range-track" aria-hidden="true">
          <span
            className="dual-range-selection"
            style={{ left: `${left}%`, width: `${Math.max(0, right - left)}%` }}
          />
        </div>
        <input
          ref={minimumInputRef}
          className="dual-range-input"
          type="range"
          name={minName}
          min="0"
          max={scaleMaximumIndex}
          step="1"
          value={safeMinimumIndex}
          aria-label={`Minimum ${label.toLocaleLowerCase()}`}
          aria-describedby={outputId}
          aria-valuemin={scaleValues[0]}
          aria-valuemax={scaleValues[scaleMaximumIndex]}
          aria-valuenow={safeMinimum}
          aria-valuetext={String(safeMinimum)}
          onChange={(event) => {
            updateHandle("minimum", Number(event.target.value));
          }}
        />
        <input
          ref={maximumInputRef}
          className="dual-range-input"
          type="range"
          name={maxName}
          min="0"
          max={scaleMaximumIndex}
          step="1"
          value={safeMaximumIndex}
          aria-label={`Maximum ${label.toLocaleLowerCase()}`}
          aria-describedby={outputId}
          aria-valuemin={scaleValues[0]}
          aria-valuemax={scaleValues[scaleMaximumIndex]}
          aria-valuenow={safeMaximum}
          aria-valuetext={String(safeMaximum)}
          onChange={(event) => {
            updateHandle("maximum", Number(event.target.value));
          }}
        />
      </div>
    </fieldset>
  );
}

export function MinimumSlider({
  label,
  name,
  value,
  bounds,
  onValueChange,
}) {
  const outputId = useId();
  const parsedValue = Number(value);
  const selectedValue = value !== "" && Number.isFinite(parsedValue)
    ? parsedValue
    : bounds.min;
  const floor = Math.min(bounds.min, selectedValue);
  const ceiling = Math.max(bounds.max, selectedValue);
  const progress = ((selectedValue - floor) / Math.max(1, ceiling - floor)) * 100;

  return (
    <fieldset className="range-filter rounded-xl border border-white/10 bg-slate-950 px-3 py-2.5">
      <legend className="sr-only">{label}</legend>
      <div className="flex items-center justify-between gap-3">
        <span className="text-sm font-semibold text-slate-200">{label}</span>
        <div className="flex items-center gap-2">
          <output
            id={outputId}
            className="text-xs font-semibold tabular-nums text-violet-200"
          >
            {value === "" ? "Any" : `${value}+`}
          </output>
          <button
            className="text-xs font-semibold text-slate-400 underline-offset-2 hover:text-white hover:underline disabled:cursor-not-allowed disabled:opacity-40"
            type="button"
            disabled={value === ""}
            onClick={() => onValueChange(name, "")}
            aria-label={`Clear ${label.toLocaleLowerCase()}`}
          >
            Clear
          </button>
        </div>
      </div>
      <div className="dual-range mt-2">
        <div className="dual-range-track" aria-hidden="true">
          <span
            className="dual-range-selection"
            data-testid={`${name}-progress`}
            style={{ width: `${progress}%` }}
          />
        </div>
        <input
          className="single-range"
          type="range"
          name={name}
          min={floor}
          max={ceiling}
          step={bounds.step}
          value={selectedValue}
          aria-label={`Minimum ${label.toLocaleLowerCase()}`}
          aria-describedby={outputId}
          onChange={(event) => onValueChange(name, event.target.value)}
        />
      </div>
    </fieldset>
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
  const [studios, setStudios] = useState([]);
  const [streamingServices, setStreamingServices] = useState([]);
  const [authors, setAuthors] = useState([]);
  const [filterRanges, setFilterRanges] = useState(DEFAULT_FILTER_RANGES);
  const [tagOptions, setTagOptions] = useState([]);
  const [tagQuery, setTagQuery] = useState("");
  const [studioQuery, setStudioQuery] = useState("");
  const [streamingQuery, setStreamingQuery] = useState("");
  const [authorQuery, setAuthorQuery] = useState("");
  const [tagsLoading, setTagsLoading] = useState(false);
  const [studiosLoading, setStudiosLoading] = useState(false);
  const [streamingServicesLoading, setStreamingServicesLoading] = useState(false);
  const [authorsLoading, setAuthorsLoading] = useState(false);
  const [genreDropdownOpen, setGenreDropdownOpen] = useState(false);
  const [studioDropdownOpen, setStudioDropdownOpen] = useState(false);
  const [streamingDropdownOpen, setStreamingDropdownOpen] = useState(false);
  const [authorDropdownOpen, setAuthorDropdownOpen] = useState(false);
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
  const studioDropdownRef = useRef(null);
  const streamingDropdownRef = useRef(null);
  const authorDropdownRef = useRef(null);
  const catalogueRequestRef = useRef(0);
  const genreRequestRef = useRef(0);
  const tagRequestRef = useRef(0);
  const studioRequestRef = useRef(0);
  const streamingRequestRef = useRef(0);
  const authorRequestRef = useRef(0);
  const rangeRequestRef = useRef(0);
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

  const loadStudios = useCallback(async (
    query = "",
    activeContentType = "ANIME",
  ) => {
    const requestId = ++studioRequestRef.current;
    setStudiosLoading(true);
    try {
      const params = new URLSearchParams({ content_type: activeContentType });
      if (query) params.set("q", query);
      const response = await fetch(`/api/v1/studios?${params}`);
      const body = await response.json();
      if (!response.ok) throw new Error(body.error?.message || "Could not load studios.");
      if (requestId === studioRequestRef.current) {
        setStudios(
          namedValues(body.items).sort((left, right) => left.localeCompare(right)),
        );
      }
    } catch {
      if (requestId === studioRequestRef.current) setStudios([]);
    } finally {
      if (requestId === studioRequestRef.current) setStudiosLoading(false);
    }
  }, []);

  const loadStreamingServices = useCallback(async (
    query = "",
    activeContentType = "ANIME",
  ) => {
    const requestId = ++streamingRequestRef.current;
    setStreamingServicesLoading(true);
    try {
      const params = new URLSearchParams({ content_type: activeContentType });
      if (query) params.set("q", query);
      const response = await fetch(`/api/v1/streaming-services?${params}`);
      const body = await response.json();
      if (!response.ok) {
        throw new Error(body.error?.message || "Could not load streaming services.");
      }
      if (requestId === streamingRequestRef.current) {
        setStreamingServices(
          namedValues(body.items).sort((left, right) => left.localeCompare(right)),
        );
      }
    } catch {
      if (requestId === streamingRequestRef.current) setStreamingServices([]);
    } finally {
      if (requestId === streamingRequestRef.current) {
        setStreamingServicesLoading(false);
      }
    }
  }, []);

  const loadAuthors = useCallback(async (
    query = "",
    activeContentType = "ALL",
  ) => {
    const requestId = ++authorRequestRef.current;
    setAuthorsLoading(true);
    try {
      const params = new URLSearchParams({ content_type: activeContentType });
      if (query) params.set("q", query);
      const response = await fetch(`/api/v1/authors?${params}`);
      const body = await response.json();
      if (!response.ok) {
        throw new Error(body.error?.message || "Could not load authors.");
      }
      if (requestId === authorRequestRef.current) {
        setAuthors(
          namedValues(body.items).sort((left, right) => left.localeCompare(right)),
        );
      }
    } catch {
      if (requestId === authorRequestRef.current) setAuthors([]);
    } finally {
      if (requestId === authorRequestRef.current) setAuthorsLoading(false);
    }
  }, []);

  const loadFilterRanges = useCallback(async (activeContentType = "ANIME") => {
    const requestId = ++rangeRequestRef.current;
    try {
      const params = new URLSearchParams({ content_type: activeContentType });
      const response = await fetch(`/api/v1/filter-ranges?${params}`);
      const body = await response.json();
      if (!response.ok) {
        throw new Error(body.error?.message || "Could not load filter ranges.");
      }
      if (requestId === rangeRequestRef.current) {
        setFilterRanges(normalizedFilterRanges(body));
      }
    } catch {
      if (requestId === rangeRequestRef.current) {
        setFilterRanges(DEFAULT_FILTER_RANGES);
      }
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
      setTagQuery("");
      setStudioQuery("");
      setStreamingQuery("");
      setAuthorQuery("");
      setGenreDropdownOpen(false);
      setStudioDropdownOpen(false);
      setStreamingDropdownOpen(false);
      setAuthorDropdownOpen(false);
      genreDropdownRef.current?.removeAttribute("open");
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
    setFilterRanges(DEFAULT_FILTER_RANGES);
    loadFilterRanges(contentType);
    if (contentType === "ANIME") {
      setStudios([]);
      setStreamingServices([]);
      loadStudios("", contentType);
      loadStreamingServices("", contentType);
      ++authorRequestRef.current;
      setAuthors([]);
      setAuthorsLoading(false);
    } else {
      ++studioRequestRef.current;
      ++streamingRequestRef.current;
      setStudios([]);
      setStreamingServices([]);
      setStudiosLoading(false);
      setStreamingServicesLoading(false);
      setAuthors([]);
      loadAuthors("", contentType);
    }
  }, [
    contentType,
    loadFilterRanges,
    loadGenres,
    loadAuthors,
    loadStreamingServices,
    loadStudios,
  ]);

  useEffect(() => {
    const closeFilterDropdowns = (event) => {
      if (!genreDropdownRef.current?.contains(event.target)) {
        genreDropdownRef.current?.removeAttribute("open");
      }
      if (!studioDropdownRef.current?.contains(event.target)) {
        setStudioDropdownOpen(false);
        setStudioQuery("");
      }
      if (!streamingDropdownRef.current?.contains(event.target)) {
        setStreamingDropdownOpen(false);
        setStreamingQuery("");
      }
      if (!authorDropdownRef.current?.contains(event.target)) {
        setAuthorDropdownOpen(false);
        setAuthorQuery("");
      }
    };
    document.addEventListener("pointerdown", closeFilterDropdowns);
    return () => document.removeEventListener("pointerdown", closeFilterDropdowns);
  }, []);

  useEffect(() => {
    if (!genreDropdownOpen) return undefined;
    const timer = window.setTimeout(
      () => loadTags(tagQuery.trim(), contentType),
      200,
    );
    return () => window.clearTimeout(timer);
  }, [contentType, genreDropdownOpen, loadTags, tagQuery]);

  useEffect(() => {
    if (!studioDropdownOpen) return undefined;
    const timer = window.setTimeout(
      () => loadStudios(studioQuery.trim(), contentType),
      200,
    );
    return () => window.clearTimeout(timer);
  }, [
    contentType,
    loadStudios,
    studioDropdownOpen,
    studioQuery,
  ]);

  useEffect(() => {
    if (!streamingDropdownOpen) return undefined;
    const timer = window.setTimeout(
      () => loadStreamingServices(streamingQuery.trim(), contentType),
      200,
    );
    return () => window.clearTimeout(timer);
  }, [
    contentType,
    loadStreamingServices,
    streamingDropdownOpen,
    streamingQuery,
  ]);

  useEffect(() => {
    if (!authorDropdownOpen) return undefined;
    const timer = window.setTimeout(
      () => loadAuthors(authorQuery.trim(), contentType),
      200,
    );
    return () => window.clearTimeout(timer);
  }, [
    authorDropdownOpen,
    authorQuery,
    contentType,
    loadAuthors,
  ]);

  const defaultFilters = filtersFor();
  const hasSelections = !filtersMatch(filters, defaultFilters);
  const defaultViewMode = contentType === "ANIME" ? "home" : "results";
  const showHomepageSections = contentType === "ANIME" && viewMode === "home";
  const hasAppliedSelections = !showHomepageSections
    && !filtersMatch(appliedFilters, defaultFilters);
  const contentDetails = contentTypeDetails(contentType);
  const filterLayout = FILTER_LAYOUTS[contentType];
  const chips = showHomepageSections
    ? []
    : activeFilterChips(appliedFilters, contentType);
  const freshness = formatFreshness(updatedAt);
  const filterPresets = presetsFor(contentType);
  const applyFilters = useCallback((nextFilters, {
    allTypesSelected = allTypesExplicitlySelected,
  } = {}) => {
    const submittedFilters = copiedFilters(nextFilters);
    const returnsHome = usesTopRatedAnimeHomepage(
      contentType,
      submittedFilters,
      allTypesSelected,
    );
    const requestFilters = returnsHome ? TOP_RATED_FILTERS : submittedFilters;
    const nextView = returnsHome ? "home" : "results";
    setFilters(submittedFilters);
    setAppliedFilters(requestFilters);
    setAllTypesExplicitlySelected(allTypesSelected);
    setViewMode(nextView);
    setActivePreset("");
    setJumpPage("");
    setPageError("");
    navigateCatalogue({
      page: 1,
      activeFilters: requestFilters,
      activeContentType: contentType,
      activeSort: sort,
      activeView: nextView,
    });
  }, [
    allTypesExplicitlySelected,
    contentType,
    navigateCatalogue,
    sort,
  ]);

  useEffect(() => {
    if (filters.q === appliedFilters.q) return undefined;
    const timer = window.setTimeout(() => {
      applyFilters(filters);
    }, 250);
    return () => window.clearTimeout(timer);
  }, [appliedFilters.q, applyFilters, filters]);

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
    setTagOptions([]);
    setTagsLoading(false);
    setActivePreset("");
    setMobileFiltersOpen(false);
    setMoreFiltersOpen(false);
    setTagQuery("");
    setStudioQuery("");
    setStreamingQuery("");
    setAuthorQuery("");
    setGenreDropdownOpen(false);
    setStudioDropdownOpen(false);
    setStreamingDropdownOpen(false);
    setAuthorDropdownOpen(false);
    genreDropdownRef.current?.removeAttribute("open");
    setJumpPage("");
    setPageError("");
    ++tagRequestRef.current;
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
    const randomFilters = copiedFilters(filters);
    setViewMode("random");
    setAppliedFilters(randomFilters);
    setLoading(true);
    setError("");
    setActivePreset("");
    try {
      const response = await fetch(
        `/api/v1/catalogue/random?${randomQueryString(
          randomFilters,
          contentType,
          6,
        )}`,
      );
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
    const { name, value } = event.target;
    const nextFilters = { ...filters, [name]: value };
    if (name === "q") {
      setActivePreset("");
      setFilters(nextFilters);
      return;
    }
    applyFilters(nextFilters, {
      allTypesSelected: name === "type" || allTypesExplicitlySelected,
    });
  };

  const changeFilterValue = (name, value) => {
    applyFilters({ ...filters, [name]: value });
  };

  const toggleMultiFilter = (name, value) => {
    applyFilters({
      ...filters,
      [name]: filters[name].includes(value)
        ? filters[name].filter((selectedValue) => selectedValue !== value)
        : [...filters[name], value],
    });
  };

  const toggleGenre = (genre) => {
    applyFilters({
      ...filters,
      genre: filters.genre.includes(genre)
        ? filters.genre.filter((selectedGenre) => selectedGenre !== genre)
        : [...filters.genre, genre],
    });
  };

  const toggleTag = (tag) => {
    toggleMultiFilter("tag", tag);
  };

  const toggleStudio = (studio) => toggleMultiFilter("studio", studio);

  const toggleStreamingService = (service) => (
    toggleMultiFilter("streaming_service", service)
  );

  const toggleAuthor = (author) => toggleMultiFilter("author", author);

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
    setTagQuery("");
    setStudioQuery("");
    setStreamingQuery("");
    setAuthorQuery("");
    setGenreDropdownOpen(false);
    setStudioDropdownOpen(false);
    setStreamingDropdownOpen(false);
    setAuthorDropdownOpen(false);
    genreDropdownRef.current?.removeAttribute("open");
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

      <section
        className={`relative z-20 mb-4 grid gap-3 rounded-2xl border border-white/10 bg-slate-900/70 p-4 shadow-xl backdrop-blur ${filterLayout.grid}`}
        aria-label="Catalogue filters"
      >
        <label>
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
              if (isOpen) {
                setStudioDropdownOpen(false);
                setStreamingDropdownOpen(false);
                setAuthorDropdownOpen(false);
                setStudioQuery("");
                setStreamingQuery("");
                setAuthorQuery("");
              }
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
              <option className="bg-slate-950" value="">Type</option>
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
            id="anime-season-filter"
            className={`${mobileFiltersOpen ? "block" : "hidden"} sm:block`}
          >
            <span className="sr-only">Season</span>
            <select
              className="filter-input !bg-slate-950"
              name="season"
              value={filters.season}
              onChange={changeFilter}
              style={{ colorScheme: "dark" }}
            >
              <option className="bg-slate-950" value="">Season</option>
              <option className="bg-slate-950" value="winter">Winter</option>
              <option className="bg-slate-950" value="spring">Spring</option>
              <option className="bg-slate-950" value="summer">Summer</option>
              <option className="bg-slate-950" value="fall">Fall</option>
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
              <option className="bg-slate-950" value="">Status</option>
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
              <option className="bg-slate-950" value="">Status</option>
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

        <div className="sm:hidden">
          <button
            className="w-full rounded-xl border border-white/15 px-3 py-3 text-sm font-semibold text-slate-200 transition hover:border-violet-400 hover:text-white"
            type="button"
            aria-controls={`genre-tag-filter${
              contentType === "ANIME"
                ? " anime-type-filter anime-status-filter anime-season-filter"
                : contentType === "ALL"
                  ? ""
                  : " print-status-filter"
            }${contentType !== "ANIME" ? " author-filter" : ""} mobile-more-filters`}
            aria-expanded={mobileFiltersOpen}
            onClick={() => setMobileFiltersOpen((open) => !open)}
          >
            Filters
          </button>
        </div>

        <div
          id="mobile-more-filters"
          className={responsiveFilterPanelClasses(
            mobileFiltersOpen,
            moreFiltersOpen,
            filterLayout.panelSpan,
            filterLayout.panelGrid,
          )}
        >
          {contentType === "ANIME" && (
            <div id="studio-filter" className="sm:col-span-1 lg:col-span-1">
              <SearchableMultiSelect
                label="Studio"
                selected={filters.studio}
                options={studios}
                query={studioQuery}
                loading={studiosLoading}
                open={studioDropdownOpen}
                dropdownRef={studioDropdownRef}
                onOpenChange={(isOpen) => {
                  setStudioDropdownOpen(isOpen);
                  if (isOpen) {
                    genreDropdownRef.current?.removeAttribute("open");
                    setGenreDropdownOpen(false);
                    setStreamingDropdownOpen(false);
                    setStreamingQuery("");
                    setAuthorDropdownOpen(false);
                    setAuthorQuery("");
                  } else {
                    setStudioQuery("");
                  }
                }}
                onQueryChange={setStudioQuery}
                onToggle={toggleStudio}
              />
            </div>
          )}

          {contentType === "ANIME" && (
            <div
              id="streaming-service-filter"
              className="sm:col-span-1 lg:col-span-1"
            >
              <SearchableMultiSelect
                label="Streaming Service"
                selected={filters.streaming_service}
                options={streamingServices}
                query={streamingQuery}
                loading={streamingServicesLoading}
                open={streamingDropdownOpen}
                dropdownRef={streamingDropdownRef}
                onOpenChange={(isOpen) => {
                  setStreamingDropdownOpen(isOpen);
                  if (isOpen) {
                    genreDropdownRef.current?.removeAttribute("open");
                    setGenreDropdownOpen(false);
                    setStudioDropdownOpen(false);
                    setStudioQuery("");
                    setAuthorDropdownOpen(false);
                    setAuthorQuery("");
                  } else {
                    setStreamingQuery("");
                  }
                }}
                onQueryChange={setStreamingQuery}
                onToggle={toggleStreamingService}
              />
            </div>
          )}

          {contentType !== "ANIME" && (
            <div id="author-filter" className="sm:col-span-1 lg:col-span-1">
              <SearchableMultiSelect
                label="Author"
                selected={filters.author}
                options={authors}
                query={authorQuery}
                loading={authorsLoading}
                open={authorDropdownOpen}
                dropdownRef={authorDropdownRef}
                onOpenChange={(isOpen) => {
                  setAuthorDropdownOpen(isOpen);
                  if (isOpen) {
                    genreDropdownRef.current?.removeAttribute("open");
                    setGenreDropdownOpen(false);
                    setStudioDropdownOpen(false);
                    setStreamingDropdownOpen(false);
                    setStudioQuery("");
                    setStreamingQuery("");
                  } else {
                    setAuthorQuery("");
                  }
                }}
                onQueryChange={setAuthorQuery}
                onToggle={toggleAuthor}
              />
            </div>
          )}

          {contentType === "ANIME" ? (
            <div className="grid gap-3 sm:col-span-2 sm:grid-cols-2 lg:col-span-5 lg:grid-cols-5">
              <MinimumSlider
                label="Score"
                name="min_score"
                value={filters.min_score}
                bounds={filterRanges.score}
                onValueChange={changeFilterValue}
              />
              <DualRangeSlider
                label="Year"
                minName="min_year"
                maxName="max_year"
                minValue={filters.min_year}
                maxValue={filters.max_year}
                bounds={filterRanges.year}
                onValueChange={changeFilterValue}
              />
              <DualRangeSlider
                label="Episodes"
                minName="min_episodes"
                maxName="max_episodes"
                minValue={filters.min_episodes}
                maxValue={filters.max_episodes}
                bounds={filterRanges.episodes}
                scale="episodes"
                onValueChange={changeFilterValue}
              />
            </div>
          ) : (
            <div className="grid gap-3 sm:col-span-2 sm:grid-cols-2 lg:col-span-5 lg:grid-cols-5">
              <MinimumSlider
                label="Score"
                name="min_score"
                value={filters.min_score}
                bounds={filterRanges.score}
                onValueChange={changeFilterValue}
              />
              <DualRangeSlider
                label="Year"
                minName="min_year"
                maxName="max_year"
                minValue={filters.min_year}
                maxValue={filters.max_year}
                bounds={filterRanges.year}
                onValueChange={changeFilterValue}
              />
              {contentType !== "ALL" && (
                <>
                  <DualRangeSlider
                    label="Chapters"
                    minName="min_chapters"
                    maxName="max_chapters"
                    minValue={filters.min_chapters}
                    maxValue={filters.max_chapters}
                    bounds={filterRanges.chapters}
                    scale="chapters"
                    onValueChange={changeFilterValue}
                  />
                  <DualRangeSlider
                    label="Volumes"
                    minName="min_volumes"
                    maxName="max_volumes"
                    minValue={filters.min_volumes}
                    maxValue={filters.max_volumes}
                    bounds={filterRanges.volumes}
                    scale="volumes"
                    onValueChange={changeFilterValue}
                  />
                </>
              )}
            </div>
          )}
        </div>

        <div className={`flex flex-wrap items-center justify-between gap-2 sm:col-span-2 ${filterLayout.panelSpan}`}>
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
            disabled={
              !hasSelections
              && !hasAppliedSelections
              && viewMode === defaultViewMode
              && sort === DEFAULT_SORT
            }
          >
            Clear selections
          </button>
        </div>
      </section>

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
