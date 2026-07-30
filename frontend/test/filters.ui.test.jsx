import { useRef, useState } from "react";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import App, {
  DualRangeSlider,
  MinimumSlider,
  SearchableMultiSelect,
} from "../src/App.jsx";


function PickerHarness() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState([]);
  const dropdownRef = useRef(null);
  return (
    <SearchableMultiSelect
      label="Studio"
      selected={selected}
      options={["Bones", "Madhouse", "MAPPA"]}
      query={query}
      loading={false}
      open={open}
      dropdownRef={dropdownRef}
      onOpenChange={setOpen}
      onQueryChange={setQuery}
      onToggle={(value) => {
        setSelected((current) => (
          current.includes(value)
            ? current.filter((entry) => entry !== value)
            : [...current, value]
        ));
      }}
    />
  );
}

function DualSliderHarness({ initialMinimum = "", initialMaximum = "" }) {
  const [minimum, setMinimum] = useState(initialMinimum);
  const [maximum, setMaximum] = useState(initialMaximum);
  const update = (name, value) => {
    if (name === "min_episodes") setMinimum(value);
    else setMaximum(value);
  };
  return (
    <DualRangeSlider
      label="Episodes"
      minName="min_episodes"
      maxName="max_episodes"
      minValue={minimum}
      maxValue={maximum}
      bounds={{ min: 1, max: 3000, step: 1 }}
      scale="episodes"
      onValueChange={update}
    />
  );
}

function MinimumSliderHarness() {
  const [score, setScore] = useState("");
  return (
    <MinimumSlider
      label="Score"
      name="min_score"
      value={score}
      bounds={{ min: 0, max: 10, step: 0.1 }}
      onValueChange={(_name, value) => setScore(value)}
    />
  );
}

function mockCatalogueFetch() {
  return vi.fn(async (input) => {
    const url = String(input);
    if (url.includes("/api/v1/anime/seasonal")) {
      return {
        ok: true,
        json: async () => ({
          items: [],
          pagination: { page: 1, pages: 1, total: 0 },
        }),
      };
    }
    if (url.includes("/api/v1/filter-ranges")) {
      return {
        ok: true,
        json: async () => ({
          ranges: {
            year: { min: 1917, max: 2027 },
            score: { min: 1.89, max: 9.46 },
            episodes: { min: 1, max: 3000 },
            chapters: { min: 1, max: 6477 },
            volumes: { min: 1, max: 200 },
          },
        }),
      };
    }
    if (
      url.includes("/api/v1/genres")
      || url.includes("/api/v1/studios")
      || url.includes("/api/v1/streaming-services")
      || url.includes("/api/v1/authors")
      || url.includes("/api/v1/tags")
    ) {
      return { ok: true, json: async () => ({ items: [] }) };
    }
    return {
      ok: true,
      json: async () => ({
        items: [],
        pagination: { page: 1, pages: 1, total: 0 },
        updated_at: null,
      }),
    };
  });
}

describe("rendered filter controls", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  test("searchable multi-select supports arrows, Enter, Escape, and focus restoration", async () => {
    const user = userEvent.setup();
    render(<PickerHarness />);

    const trigger = screen.getByRole("button", { name: "Studio" });
    await user.click(trigger);
    const search = screen.getByRole("combobox", { name: "Search studio" });
    expect(search).toHaveFocus();

    await user.keyboard("{ArrowDown}{Enter}");
    expect(
      screen.getByRole("option", { name: "Madhouse" }),
    ).toHaveAttribute("aria-selected", "true");

    await user.keyboard("{Escape}");
    await waitFor(() => expect(
      screen.getByRole("button", { name: "Studio (1)" }),
    ).toHaveFocus());
  });

  test("the entire dual-slider track accepts pointer input", () => {
    render(<DualSliderHarness />);
    const track = screen.getByTestId("min_episodes-max_episodes-track");
    vi.spyOn(track, "getBoundingClientRect").mockReturnValue({
      left: 0,
      right: 300,
      top: 0,
      bottom: 44,
      width: 300,
      height: 44,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    });

    fireEvent.pointerDown(track, { clientX: 90, pointerId: 1 });

    expect(screen.queryByText("Any")).not.toBeInTheDocument();
    expect(screen.getByText(/\+$/)).toBeInTheDocument();
  });

  test("a pointer can separate coincident dual-slider handles", () => {
    render(<DualSliderHarness initialMinimum="24" initialMaximum="24" />);
    const track = screen.getByTestId("min_episodes-max_episodes-track");
    vi.spyOn(track, "getBoundingClientRect").mockReturnValue({
      left: 0,
      right: 300,
      top: 0,
      bottom: 44,
      width: 300,
      height: 44,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    });
    const maximum = screen.getByRole("slider", {
      name: "Maximum episodes",
    });
    const coincidentPosition = (
      Number(maximum.value) / Number(maximum.max)
    ) * 300;

    fireEvent.pointerDown(track, {
      clientX: coincidentPosition + 40,
      pointerId: 2,
    });

    expect(Number(maximum.getAttribute("aria-valuenow"))).toBeGreaterThan(24);
  });

  test("score uses a clean clearable 0–10 scale", async () => {
    const user = userEvent.setup();
    render(<MinimumSliderHarness />);
    const score = screen.getByRole("slider", { name: "Minimum score" });

    expect(score).toHaveAttribute("min", "0");
    expect(score).toHaveAttribute("max", "10");
    expect(score).toHaveAttribute("step", "0.1");
    expect(screen.getByText("Any")).toBeInTheDocument();

    fireEvent.change(score, { target: { value: "7" } });
    expect(screen.getByText("7+")).toBeInTheDocument();
    expect(screen.getByTestId("min_score-progress")).toHaveStyle({
      width: "70%",
    });
    await user.click(screen.getByRole("button", { name: "Clear score" }));
    expect(screen.getByText("Any")).toBeInTheDocument();
  });
});

describe("catalogue filter integration", () => {
  let fetchMock;

  beforeEach(() => {
    fetchMock = mockCatalogueFetch();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    window.history.replaceState({}, "", "/");
  });

  test("clearing a filter automatically clears its applied result state", async () => {
    const user = userEvent.setup();
    window.history.replaceState(
      {},
      "",
      "/?content_type=MANGA&min_score=8",
    );
    render(<App />);

    expect(await screen.findByText("Score: 8+")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Clear score" }));

    expect(screen.getByRole("button", {
      name: "Clear selections",
    })).toBeDisabled();
  });

  test("Season replaces Search and filter changes load results automatically", async () => {
    const user = userEvent.setup();
    render(<App />);

    expect(screen.queryByRole("button", { name: "Search" })).toBeNull();
    const season = screen.getByRole("combobox", { name: "Season" });
    await user.selectOptions(season, "summer");

    await waitFor(() => expect(fetchMock.mock.calls.some(([input]) => {
      const request = new URL(String(input), "https://kyoquan.test");
      return request.pathname === "/api/v1/catalogue"
        && request.searchParams.get("season") === "summer";
    })).toBe(true));

    const search = screen.getByRole("textbox", { name: "Search catalogue" });
    await user.type(search, "Frieren");
    await waitFor(() => expect(fetchMock.mock.calls.some(([input]) => {
      const request = new URL(String(input), "https://kyoquan.test");
      return request.pathname === "/api/v1/catalogue"
        && request.searchParams.get("q") === "Frieren";
    })).toBe(true));
  });

  test("All content exposes only cross-catalogue filters", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/?content_type=ALL");
    render(<App />);

    await user.click(screen.getByRole("button", { name: "More filters" }));
    expect(screen.getByRole("slider", { name: "Minimum score" })).toBeInTheDocument();
    expect(screen.getByRole("slider", { name: "Minimum year" })).toBeInTheDocument();
    expect(screen.queryByRole("slider", { name: "Minimum episodes" })).toBeNull();
    expect(screen.queryByRole("slider", { name: "Minimum chapters" })).toBeNull();
    expect(screen.queryByRole("slider", { name: "Minimum volumes" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Studio" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Streaming Service" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Author" })).toBeNull();
  });

  test("Manga authors support searching, selection, chips, and URL state", async () => {
    const user = userEvent.setup();
    fetchMock.mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/api/v1/authors")) {
        return {
          ok: true,
          json: async () => ({ items: ["Hiromu Arakawa", "SIU"] }),
        };
      }
      return mockCatalogueFetch()(input);
    });
    window.history.replaceState({}, "", "/?content_type=MANGA");
    render(<App />);

    await user.click(screen.getByRole("button", { name: "More filters" }));
    await user.click(await screen.findByRole("button", { name: "Author" }));
    const search = screen.getByRole("combobox", { name: "Search author" });
    await user.type(search, "Hiromu");
    await user.click(await screen.findByRole("option", {
      name: "Hiromu Arakawa",
    }));

    expect(await screen.findByText("Author: Hiromu Arakawa")).toBeInTheDocument();
    expect(new URLSearchParams(window.location.search).get("author")).toBe(
      "Hiromu Arakawa",
    );
    expect(fetchMock.mock.calls.some(([input]) => {
      const request = new URL(String(input), "https://kyoquan.test");
      return request.pathname === "/api/v1/catalogue"
        && request.searchParams.get("author") === "Hiromu Arakawa";
    })).toBe(true);
  });

  test("Manga details display author names and roles", async () => {
    const user = userEvent.setup();
    fetchMock.mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/api/v1/catalogue/MANGA/1")) {
        return {
          ok: true,
          json: async () => ({
            item: {
              mal_id: 1,
              content_type: "MANGA",
              title: "Example Manga",
              genres: [],
              authors: [
                { name: "Hiromu Arakawa", role: "Story & Art" },
              ],
            },
          }),
        };
      }
      if (url.includes("/api/v1/catalogue?")) {
        return {
          ok: true,
          json: async () => ({
            items: [{
              mal_id: 1,
              content_type: "MANGA",
              title: "Example Manga",
              genres: [],
              authors: [],
            }],
            pagination: { page: 1, pages: 1, total: 1 },
            updated_at: null,
          }),
        };
      }
      return mockCatalogueFetch()(input);
    });
    window.history.replaceState({}, "", "/?content_type=MANGA");
    render(<App />);

    await user.click(await screen.findByText("Example Manga"));

    expect(await screen.findByText("Author:")).toBeInTheDocument();
    expect(screen.getByText("Hiromu Arakawa (Story & Art)")).toBeInTheDocument();
  });

  test("mobile Filters reveals the responsive slider panel", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/?content_type=MANHWA");
    render(<App />);
    const panel = document.getElementById("mobile-more-filters");

    expect(panel).toHaveClass("hidden");
    await user.click(screen.getByRole("button", { name: "Filters" }));
    expect(panel).toHaveClass("grid");
    expect(screen.getByRole("slider", {
      name: "Minimum score",
    })).toBeInTheDocument();
  });
});
