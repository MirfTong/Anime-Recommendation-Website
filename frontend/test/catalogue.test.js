import assert from "node:assert/strict";
import test from "node:test";

import {
  TOP_RATED_FILTERS,
  filtersFor,
  filtersMatch,
  itemContentType,
  itemMetadata,
  queryString,
  usesTopRatedAnimeHomepage,
  visiblePageNumbers,
} from "../src/catalogue.js";


test("clear filters are visually blank while the anime homepage stays TV-ranked", () => {
  const cleared = filtersFor("ANIME");

  assert.equal(cleared.type, "");
  assert.equal(cleared.genre.length, 0);
  assert.equal(cleared.tag.length, 0);
  assert.equal(TOP_RATED_FILTERS.type, "TV");
  assert.equal(filtersMatch(cleared, filtersFor("MANGA")), true);
});

test("explicitly choosing all anime types leaves the TV-only homepage", () => {
  const cleared = filtersFor("ANIME");

  assert.equal(usesTopRatedAnimeHomepage("ANIME", cleared), true);
  assert.equal(usesTopRatedAnimeHomepage("ANIME", cleared, true), false);
});

test("anime queries send anime filters and omit readable-title filters", () => {
  const filters = {
    ...filtersFor(),
    q: "monster",
    type: "TV",
    season: "spring",
    min_episodes: "12",
    min_chapters: "50",
    genre: ["Drama", "Mystery"],
  };
  const params = new URLSearchParams(queryString(filters, 3, "ANIME"));

  assert.equal(params.get("content_type"), "ANIME");
  assert.equal(params.get("page"), "3");
  assert.equal(params.get("type"), "TV");
  assert.equal(params.get("season"), "spring");
  assert.equal(params.get("min_episodes"), "12");
  assert.equal(params.get("genre"), "Drama,Mystery");
  assert.equal(params.has("min_chapters"), false);
});

test("manga and manhwa queries send print filters and omit anime filters", () => {
  for (const contentType of ["MANGA", "MANHWA"]) {
    const filters = {
      ...filtersFor(),
      status: "PUBLISHING",
      min_chapters: "25",
      min_volumes: "3",
      min_episodes: "12",
      type: "TV",
      tag: ["school"],
    };
    const params = new URLSearchParams(queryString(filters, 1, contentType));

    assert.equal(params.get("content_type"), contentType);
    assert.equal(params.get("status"), "PUBLISHING");
    assert.equal(params.get("min_chapters"), "25");
    assert.equal(params.get("min_volumes"), "3");
    assert.equal(params.get("tag"), "school");
    assert.equal(params.has("min_episodes"), false);
    assert.equal(params.has("type"), false);
  }
});

test("all-content queries retain only shared filters", () => {
  const filters = {
    ...filtersFor(),
    q: "hero",
    min_score: "7",
    min_year: "2000",
    type: "TV",
    status: "PUBLISHING",
  };
  const params = new URLSearchParams(queryString(filters, 1, "ALL"));

  assert.equal(params.get("q"), "hero");
  assert.equal(params.get("min_score"), "7");
  assert.equal(params.get("min_year"), "2000");
  assert.equal(params.has("type"), false);
  assert.equal(params.has("status"), false);
});

test("cards use episodes for anime and chapters plus volumes for print media", () => {
  assert.deepEqual(
    itemMetadata({
      content_type: "ANIME",
      type: "TV",
      season: "spring",
      year: 2014,
      episodes: 24,
    }),
    ["TV", "Spring", 2014, "24 eps"],
  );
  assert.deepEqual(
    itemMetadata({
      content_type: "MANHWA",
      status: "ON_HIATUS",
      publication_year: 2020,
      chapters: 50,
      volumes: 4,
    }),
    ["Manhwa", "On Hiatus", 2020, "50 ch", "4 vols"],
  );
  assert.equal(itemContentType({ content_type: "manga" }), "MANGA");
});

test("pagination keeps a stable eight-page window", () => {
  assert.deepEqual(visiblePageNumbers(1, 20), [1, 2, 3, 4, 5, 6, 7, 8]);
  assert.deepEqual(
    visiblePageNumbers(20, 20),
    [13, 14, 15, 16, 17, 18, 19, 20],
  );
});
