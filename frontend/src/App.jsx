import { useCallback, useEffect, useRef, useState } from "react";

const EMPTY_FILTERS = {
  q: "",
  min_score: "",
  min_year: "",
  max_year: "",
  min_episodes: "",
  type: "",
  genre: [],
};

function queryString(filters, page = 1) {
  const params = new URLSearchParams({ page: String(page), per_page: "24" });
  Object.entries(filters).forEach(([key, value]) => {
    if (Array.isArray(value) ? value.length > 0 : value) params.set(key, value);
  });
  return params.toString();
}

function Score({ value }) {
  return <span className="rounded-full bg-amber-300/15 px-2.5 py-1 text-sm font-bold text-amber-300">★ {value?.toFixed(2) ?? "—"}</span>;
}

function AnimeCard({ anime, onSelect }) {
  return (
    <button
      className="group overflow-hidden rounded-2xl border border-white/10 bg-slate-900/80 text-left shadow-lg transition hover:-translate-y-1 hover:border-violet-400/60 hover:shadow-glow focus:outline-none focus:ring-2 focus:ring-violet-400"
      onClick={() => onSelect(anime.mal_id)}
      type="button"
    >
      <div className="relative aspect-[2/3] overflow-hidden bg-slate-800">
        <img className="h-full w-full object-cover transition duration-300 group-hover:scale-105" src={anime.image_url} alt={`${anime.title} cover`} loading="lazy" />
        <div className="absolute bottom-3 left-3"><Score value={anime.score} /></div>
      </div>
      <div className="space-y-2 p-4">
        <h2 className="line-clamp-2 min-h-12 text-base font-bold text-white">{anime.title}</h2>
        <p className="text-sm text-slate-400">{anime.type} · {anime.year ?? "Unknown year"} · {anime.episodes ?? "?"} eps</p>
        <div className="flex flex-wrap gap-1.5">
          {anime.genres.slice(0, 3).map((genre) => <span key={genre} className="rounded-full bg-violet-400/10 px-2 py-1 text-xs text-violet-200">{genre}</span>)}
        </div>
      </div>
    </button>
  );
}

function DetailModal({ anime, onClose }) {
  if (!anime) return null;
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-slate-950/85 p-4 backdrop-blur-sm" role="dialog" aria-modal="true" aria-label={anime.title}>
      <article className="relative max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-3xl border border-white/10 bg-slate-900 shadow-2xl">
        <button className="absolute right-4 top-4 rounded-full bg-slate-950/80 px-3 py-1 text-xl text-white hover:bg-violet-600" onClick={onClose} type="button" aria-label="Close details">×</button>
        <div className="grid gap-6 p-6 sm:grid-cols-[12rem_1fr]">
          <img className="w-full rounded-2xl object-cover" src={anime.image_url} alt={`${anime.title} cover`} />
          <div className="space-y-4">
            <div><p className="text-sm font-semibold uppercase tracking-widest text-violet-300">Anime details</p><h2 className="mt-1 text-3xl font-black text-white">{anime.title}</h2>{anime.alternative_title && <p className="mt-1 text-slate-400">{anime.alternative_title}</p>}</div>
            <div className="flex flex-wrap items-center gap-2"><Score value={anime.score} /><span className="text-slate-300">{anime.type} · {anime.year ?? "Unknown year"} · {anime.episodes ?? "?"} episodes</span></div>
            <div className="flex flex-wrap gap-2">{anime.genres.map((genre) => <span key={genre} className="rounded-full bg-violet-400/10 px-3 py-1 text-sm text-violet-100">{genre}</span>)}</div>
            {anime.genres_detailed?.length > 0 && <p className="text-sm leading-6 text-slate-400">Tags: {anime.genres_detailed.join(", ")}</p>}
            <a className="inline-flex rounded-xl bg-violet-500 px-4 py-2 font-bold text-white transition hover:bg-violet-400" href={anime.mal_url} target="_blank" rel="noreferrer">View on MyAnimeList ↗</a>
          </div>
        </div>
      </article>
    </div>
  );
}

export default function App() {
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [genres, setGenres] = useState([]);
  const [anime, setAnime] = useState([]);
  const [pagination, setPagination] = useState({ page: 1, pages: 1, total: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState(null);
  const genreDropdownRef = useRef(null);

  const loadAnime = useCallback(async (page = 1, activeFilters = filters) => {
    setLoading(true); setError("");
    try {
      const response = await fetch(`/api/v1/anime?${queryString(activeFilters, page)}`);
      const body = await response.json();
      if (!response.ok) throw new Error(body.error?.message || "Could not load anime.");
      setAnime(body.items); setPagination(body.pagination);
    } catch (requestError) { setError(requestError.message); } finally { setLoading(false); }
  }, [filters]);

  useEffect(() => {
    fetch("/api/v1/genres").then((response) => response.json()).then((body) => setGenres(body.items ?? [])).catch(() => setGenres([]));
    loadAnime(1, EMPTY_FILTERS);
  }, []); // Initial catalogue only; filters are submitted explicitly.

  useEffect(() => {
    const closeGenreDropdown = (event) => {
      if (!genreDropdownRef.current?.contains(event.target)) {
        genreDropdownRef.current?.removeAttribute("open");
      }
    };
    document.addEventListener("pointerdown", closeGenreDropdown);
    return () => document.removeEventListener("pointerdown", closeGenreDropdown);
  }, []);

  const submitFilters = (event) => { event.preventDefault(); loadAnime(1); };
  const showRandom = async () => {
    setLoading(true); setError("");
    try {
      const response = await fetch("/api/v1/anime/random?limit=6"); const body = await response.json();
      if (!response.ok) throw new Error(body.error?.message || "Could not load random anime.");
      setAnime(body.items); setPagination({ page: 1, pages: 1, total: body.items.length });
    } catch (requestError) { setError(requestError.message); } finally { setLoading(false); }
  };
  const openDetail = async (malId) => {
    try {
      const response = await fetch(`/api/v1/anime/${malId}`); const body = await response.json();
      if (!response.ok) throw new Error(body.error?.message || "Could not load details."); setSelected(body.item);
    } catch (requestError) { setError(requestError.message); }
  };
  const changeFilter = (event) => setFilters((current) => ({ ...current, [event.target.name]: event.target.value }));
  const toggleGenre = (genre) => setFilters((current) => ({
    ...current,
    genre: current.genre.includes(genre)
      ? current.genre.filter((selectedGenre) => selectedGenre !== genre)
      : [...current.genre, genre],
  }));
  const clearSelections = () => {
    setFilters({ ...EMPTY_FILTERS, genre: [] });
    loadAnime(1, EMPTY_FILTERS);
  };
  const hasSelections = Object.values(filters).some((value) => Array.isArray(value) ? value.length > 0 : Boolean(value));

  return (
    <main className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
      <header className="mb-10 flex flex-col gap-6 sm:flex-row sm:items-end sm:justify-between">
        <div><p className="font-semibold uppercase tracking-[0.3em] text-violet-300">Discover your next favorite anime</p><h1 className="mt-2 text-4xl font-black tracking-tight text-white sm:text-6xl">KyoQuan</h1><p className="mt-3 max-w-xl text-slate-300">Search a living catalogue of anime, refreshed with current seasonal data.</p></div>
        <button className="rounded-xl bg-white px-5 py-3 font-bold text-slate-950 transition hover:bg-violet-200" onClick={showRandom} type="button">Randomize</button>
      </header>

      <form className="mb-8 grid gap-3 rounded-2xl border border-white/10 bg-slate-900/70 p-4 shadow-xl backdrop-blur sm:grid-cols-2 lg:grid-cols-4" onSubmit={submitFilters}>
        <input className="filter-input sm:col-span-2" name="q" placeholder="Search anime" value={filters.q} onChange={changeFilter} />
        <div className="relative">
          <details ref={genreDropdownRef} className="group">
            <summary className="filter-input flex cursor-pointer list-none items-center justify-between marker:hidden">
              <span>{filters.genre.length ? `${filters.genre.length} genres selected` : "All genres"}</span>
              <span className="text-violet-300 transition group-open:rotate-180">⌄</span>
            </summary>
            <div className="absolute z-20 mt-2 max-h-64 w-full overflow-y-auto rounded-xl border border-white/10 bg-slate-950 p-1 shadow-2xl">
              {genres.map((genre) => (
                <button key={genre} className={`block w-full rounded-lg px-3 py-2 text-left text-sm transition ${filters.genre.includes(genre) ? "bg-violet-500 text-white" : "text-slate-300 hover:bg-violet-400/10"}`} type="button" aria-pressed={filters.genre.includes(genre)} onClick={() => toggleGenre(genre)}>
                  {genre}
                </button>
              ))}
            </div>
          </details>
        </div>
        <select className="filter-input" name="type" value={filters.type} onChange={changeFilter}><option value="">All types</option><option value="TV">TV</option><option value="MOVIE">Movie</option><option value="OVA">OVA</option><option value="ONA">ONA</option><option value="SPECIAL">Special</option></select>
        <input className="filter-input" name="min_score" inputMode="decimal" min="0" max="10" step="0.1" placeholder="Minimum score" value={filters.min_score} onChange={changeFilter} />
        <input className="filter-input" name="min_year" inputMode="numeric" placeholder="From year" value={filters.min_year} onChange={changeFilter} />
        <input className="filter-input" name="max_year" inputMode="numeric" placeholder="To year" value={filters.max_year} onChange={changeFilter} />
        <input className="filter-input" name="min_episodes" inputMode="numeric" placeholder="Minimum episodes" value={filters.min_episodes} onChange={changeFilter} />
        <div className="flex justify-end gap-2 sm:col-span-2 lg:col-span-4"><button className="rounded-xl border border-white/15 px-3 py-2 text-xs font-semibold text-slate-200 transition hover:border-violet-400 hover:text-white disabled:cursor-not-allowed disabled:opacity-40" type="button" onClick={clearSelections} disabled={!hasSelections}>Clear selections</button><button className="rounded-xl bg-violet-500 px-3 py-2 text-sm font-bold text-white hover:bg-violet-400" type="submit">Search</button></div>
      </form>

      {error && <div className="mb-6 rounded-xl border border-rose-400/40 bg-rose-950/60 p-4 text-rose-100">{error}</div>}
      {!loading && !error && <p className="mb-5 text-sm text-slate-400">{pagination.total.toLocaleString()} anime found</p>}
      {loading ? <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">{Array.from({ length: 12 }, (_, index) => <div key={index} className="aspect-[2/3] animate-pulse rounded-2xl bg-slate-800" />)}</div> : anime.length > 0 ? <section className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6">{anime.map((entry) => <AnimeCard key={entry.id} anime={entry} onSelect={openDetail} />)}</section> : !error && <div className="rounded-2xl border border-dashed border-slate-600 p-12 text-center text-slate-300">No anime match those filters. Try widening your search.</div>}
      {!loading && pagination.pages > 1 && <nav className="mt-10 flex items-center justify-center gap-4"><button className="rounded-lg border border-white/15 px-4 py-2 disabled:opacity-40" disabled={pagination.page === 1} onClick={() => loadAnime(pagination.page - 1)} type="button">Previous</button><span className="text-slate-400">Page {pagination.page} of {pagination.pages}</span><button className="rounded-lg border border-white/15 px-4 py-2 disabled:opacity-40" disabled={pagination.page === pagination.pages} onClick={() => loadAnime(pagination.page + 1)} type="button">Next</button></nav>}
      <DetailModal anime={selected} onClose={() => setSelected(null)} />
    </main>
  );
}
