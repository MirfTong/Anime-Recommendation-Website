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
    await user.click(screen.getByRole("button", { name: "Clear score" }));
    expect(screen.getByText("Any")).toBeInTheDocument();
  });
});

describe("catalogue filter integration", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", mockCatalogueFetch());
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    window.history.replaceState({}, "", "/");
  });

  test("Clear Selections stays enabled while applied print filters remain", async () => {
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
    })).toBeEnabled();
  });

  test("All content warns when anime-only and print-only filters conflict", async () => {
    window.history.replaceState(
      {},
      "",
      "/?content_type=ALL&min_episodes=12&min_chapters=10",
    );
    render(<App />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Anime-only and print-only filters cannot match the same title",
    );
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
