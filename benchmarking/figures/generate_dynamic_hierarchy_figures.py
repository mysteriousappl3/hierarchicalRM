"""Figures for the dynamic (n-level) hierarchy results.

Reads benchmarking/results/ directly so the figures regenerate from data rather
than from hardcoded numbers.

    python benchmarking/figures/generate_dynamic_hierarchy_figures.py

Palette: dataviz reference categorical slots 1/2/3/7. Validated all-pairs in
light mode (worst CVD dE 9.2 deutan, worst normal-vision dE 16.3).
Light surface only: these render into a fixed-background deck, not a themeable page.
"""

from __future__ import annotations

import glob
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

HERE = Path(__file__).resolve().parent
RESULTS = HERE.parent / "results" / "gpt-5.5"
TASKS = [f"hanoi_{n}" for n in range(3, 13)]
RINGS = list(range(3, 13))

# --- palette -----------------------------------------------------------------
SERIES = {
    "direct": "#2a78d6",
    "inner-outer": "#eb6834",
    "hierarchy (2-level)": "#1baf7a",
    "dynamic (n-level)": "#4a3aa7",
}
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
BASELINE = "#c3c2b7"
CRITICAL = "#d03b3b"

plt.rcParams.update({
    "font.family": ["Segoe UI", "DejaVu Sans", "sans-serif"],
    "figure.facecolor": SURFACE,
    "axes.facecolor": SURFACE,
    "savefig.facecolor": SURFACE,
    "text.color": INK,
    "axes.labelcolor": INK2,
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "axes.edgecolor": BASELINE,
    "axes.linewidth": 1.0,
    "grid.color": GRID,
    "grid.linewidth": 1.0,
})


def load(mode: str, effort=None) -> dict:
    out = {}
    for task in TASKS:
        best = None
        for path in sorted(glob.glob(str(RESULTS / mode / f"{task}_*" / "metrics.json"))):
            with open(path, encoding="utf-8") as handle:
                m = json.load(handle)
            if effort is not None and str(m["reasoning_effort"]) != effort:
                continue
            best = m
        if best:
            out[task] = best
    return out


DATA = {
    "direct": load("not-hierarchy"),
    "inner-outer": load("inner-outer"),
    "hierarchy (2-level)": load("hierarchy"),
    "dynamic (n-level)": load("dynamic-hierarchy", effort="low"),
}


def tidy(ax, ylabel="", xlabel=""):
    ax.set_axisbelow(True)
    ax.grid(axis="y", linewidth=1.0)
    ax.grid(axis="x", visible=False)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.spines["left"].set_color(BASELINE)
    ax.spines["bottom"].set_color(BASELINE)
    ax.set_ylabel(ylabel, fontsize=10, color=INK2)
    ax.set_xlabel(xlabel, fontsize=10, color=INK2)
    ax.tick_params(length=0, labelsize=9)


# --- figure 1: framework ------------------------------------------------------
def framework_figure(path: Path) -> None:
    fig, ax = plt.subplots(figsize=(13.0, 6.8), dpi=200)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")

    def box(x, y, w, h, label, sub="", fc="#ffffff", ec=BASELINE, bold=False, tc=INK):
        ax.add_patch(FancyBboxPatch(
            (x, y), w, h, boxstyle="round,pad=0.6,rounding_size=1.6",
            facecolor=fc, edgecolor=ec, linewidth=1.6 if bold else 1.1))
        ax.text(x + w / 2, y + h / 2 + (1.5 if sub else 0), label,
                ha="center", va="center", fontsize=9.5,
                fontweight="bold" if bold else "normal", color=tc)
        if sub:
            ax.text(x + w / 2, y + h / 2 - 3.0, sub, ha="center", va="center",
                    fontsize=7.8, color=INK2)

    def arrow(x1, y1, x2, y2, color=MUTED, style="-|>", ls="-", lw=1.6, rad=0.0):
        ax.add_patch(FancyArrowPatch(
            (x1, y1), (x2, y2), arrowstyle=style, mutation_scale=11,
            color=color, linewidth=lw, linestyle=ls,
            connectionstyle=f"arc3,rad={rad}", shrinkA=1, shrinkB=1))

    ax.text(0, 96, "Dynamic (n-level) hierarchy pipeline", fontsize=14,
            fontweight="bold", color=INK)
    ax.text(0, 91.5, "Planning and hierarchy composition are separate stages. "
                     "Levels are inferred from the call graph, never declared.",
            fontsize=9.5, color=INK2)

    y, h = 70, 13
    box(0, y, 14, h, "Scene / State", "descriptor", fc="#f4f4f1")
    box(17, y, 14, h, "InnerBot", "state check", fc="#f4f4f1")
    box(34, y, 12, h, "H1 generator", "one legal move", fc="#f4f4f1")
    box(49, y, 18, h, "DecisionBot", "subtasks + goal states\n(natural language only)",
        fc="#eef2fb", ec=SERIES["direct"], bold=True)
    box(70, y, 22, h, "DynamicHierarchyAgent", "composes H2 … Hn",
        fc="#efedf7", ec=SERIES["dynamic (n-level)"], bold=True)
    for x1, x2 in [(14, 17), (31, 34), (46, 49), (67, 70)]:
        arrow(x1, y + h / 2, x2, y + h / 2)

    y2 = 44
    box(70, y2, 22, h, "Symbolic validation", "expand → simulate\n(Python, no LLM)",
        fc="#eaf7f1", ec=SERIES["hierarchy (2-level)"])
    box(45, y2, 21, h, "InnerBot router", "RESULT / OWNER / REASON",
        fc="#fdefe9", ec=SERIES["inner-outer"], bold=True)
    arrow(81, y, 81, y2 + h)
    arrow(70, y2 + h / 2, 66, y2 + h / 2)

    y3 = 18
    box(45, y3, 21, h, "Execute", "symbolic H0 moves", fc="#f4f4f1")
    box(70, y3, 22, h, "OuterBot", "per-subtask verify", fc="#f4f4f1")
    arrow(55.5, y2, 55.5, y3 + h)
    arrow(66, y3 + h / 2, 70, y3 + h / 2)

    # correction routing: two owner branches back up
    arrow(50, y2 + h, 55, y - 0.5, color=SERIES["direct"], ls=(0, (4, 3)), rad=-0.22)
    arrow(62, y2 + h, 74, y - 0.5, color=SERIES["dynamic (n-level)"], ls=(0, (4, 3)), rad=0.22)

    # OuterBot finding loops back to the router. Only the last segment carries a
    # head — an arrowhead per segment reads as four separate arrows.
    for seg in [(81, y3, 81, 10), (81, 10, 38.5, 10), (38.5, 10, 38.5, y2 + h / 2)]:
        arrow(*seg, color=CRITICAL, ls=(0, (4, 3)), lw=1.4, style="-")
    arrow(38.5, y2 + h / 2, 45, y2 + h / 2, color=CRITICAL, ls=(0, (4, 3)), lw=1.4)
    ax.text(60, 6.6, "OuterBot finding → re-diagnosed by the router",
            ha="center", fontsize=8, color=CRITICAL)

    # owner legend
    ax.add_patch(FancyBboxPatch((0, 10), 34, 32, boxstyle="round,pad=0.8,rounding_size=1.6",
                                facecolor="#f4f4f1", edgecolor=BASELINE, linewidth=1.1))
    ax.text(2.5, 38.4, "Correction routing", fontsize=10, fontweight="bold", color=INK)
    ax.text(2.5, 34.8, "The router's OWNER field decides who re-runs:",
            fontsize=8.2, color=INK2)
    rows = [
        (SERIES["direct"], "DecisionBot", "re-plan, then rebuild hierarchy"),
        (SERIES["dynamic (n-level)"], "HierarchyPlanner", "keep plan, rebuild hierarchy only"),
        (MUTED, "both", "same path as DecisionBot"),
    ]
    for i, (color, owner, effect) in enumerate(rows):
        yy = 30.4 - i * 4.6
        ax.plot([3.4], [yy], "o", color=color, markersize=5.5, clip_on=False)
        ax.text(5.4, yy, owner, fontsize=8.2, color=INK, va="center", fontweight="bold")
        ax.text(5.4, yy - 2.2, effect, fontsize=7.6, color=INK2, va="center")
    ax.text(2.5, 12.4, "Symbolic failures skip the router entirely: the plan holds\n"
                       "no function calls, so it cannot be the cause.",
            fontsize=7.8, color=INK2, va="bottom")

    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


# --- figure 2: cost and failure ----------------------------------------------
def comparison_figure(path: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(13.0, 5.2), dpi=200)

    ax = axes[0]
    for name, color in SERIES.items():
        rows = [DATA[name].get(t) for t in TASKS]
        xs = [r for r, m in zip(RINGS, rows) if m]
        ys = [m["output_tokens"] for m in rows if m]
        ax.plot(xs, ys, color=color, linewidth=2.0, zorder=3, label=name)
        sx = [r for r, m in zip(RINGS, rows) if m and m["solved"]]
        sy = [m["output_tokens"] for m in rows if m and m["solved"]]
        ax.plot(sx, sy, "o", color=color, markersize=6.5, zorder=4,
                markeredgecolor=SURFACE, markeredgewidth=1.6)
        fx = [r for r, m in zip(RINGS, rows) if m and not m["solved"]]
        fy = [m["output_tokens"] for m in rows if m and not m["solved"]]
        ax.plot(fx, fy, "X", color=color, markersize=9.5, zorder=5,
                markeredgecolor=SURFACE, markeredgewidth=1.4)
    ax.set_yscale("log")
    ax.set_xticks(RINGS)
    tidy(ax, "output tokens (log)", "rings")
    ax.set_title("Cost per task    ●solved  ✕failed", fontsize=11,
                 color=INK, loc="left", fontweight="bold", pad=10)
    ax.legend(frameon=False, fontsize=8.5, loc="upper left", labelcolor=INK2)

    # Bars, not lines: three series sit at zero for the small tasks and lines
    # would hide each other there. "direct" is excluded — a single call has no
    # correction loop, so its zero is structural rather than earned.
    ax = axes[1]
    bar_modes = ["inner-outer", "hierarchy (2-level)", "dynamic (n-level)"]
    width = 0.26
    for i, name in enumerate(bar_modes):
        offset = (i - 1) * width
        rows = [DATA[name].get(t) for t in TASKS]
        ax.bar([r + offset for r, m in zip(RINGS, rows) if m],
               [m["replan_count"] for m in rows if m],
               width=width * 0.88, color=SERIES[name], zorder=3, label=name)
    ax.axhline(15, color=CRITICAL, linewidth=1.4, linestyle=(0, (4, 3)), zorder=2)
    ax.text(2.6, 15.5, "replan budget exhausted", fontsize=8, color=CRITICAL)
    ax.set_xticks(RINGS)
    ax.set_ylim(0, 17.5)
    tidy(ax, "replans", "rings")
    ax.set_title("Correction rounds needed", fontsize=11, color=INK,
                 loc="left", fontweight="bold", pad=10)
    ax.text(0.5, -0.20, "direct excluded: one call, no correction loop",
            transform=ax.transAxes, fontsize=8, color=MUTED, ha="center")
    ax.text(6.9, 12.4, "dynamic (n-level) draws no bars:\n0 replans on every task",
            fontsize=8.6, color=SERIES["dynamic (n-level)"], va="top")
    ax.legend(frameon=False, fontsize=8.5, loc="lower left", labelcolor=INK2)

    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


# --- figure 3: how many layers -----------------------------------------------
def depth_figure(path: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(13.0, 5.2), dpi=200)
    dyn = DATA["dynamic (n-level)"]

    ax = axes[0]
    depths = [dyn[t]["max_hierarchy_level"] for t in TASKS]
    ax.plot(RINGS, RINGS, color=MUTED, linewidth=1.4, linestyle=(0, (4, 3)),
            zorder=2, label="one level per ring")
    ax.plot(RINGS, depths, color=SERIES["dynamic (n-level)"], linewidth=2.0,
            marker="o", markersize=7, markeredgecolor=SURFACE, markeredgewidth=1.6,
            zorder=4, label="dynamic (n-level)")
    ax.plot(RINGS, [2] * len(RINGS), color=SERIES["hierarchy (2-level)"],
            linewidth=2.0, zorder=3, label="hierarchy (fixed at 2)")
    for x, d in zip(RINGS, depths):
        ax.annotate(str(d), (x, d), textcoords="offset points", xytext=(0, 9),
                    ha="center", fontsize=8, color=INK2)
    ax.set_xticks(RINGS)
    ax.set_ylim(0, 14)
    tidy(ax, "hierarchy depth chosen", "rings")
    ax.set_title("Depth is chosen by the agent, not configured", fontsize=11,
                 color=INK, loc="left", fontweight="bold", pad=10)
    ax.legend(frameon=False, fontsize=8.5, loc="upper left", labelcolor=INK2)

    ax = axes[1]
    lc = {int(k): v for k, v in dyn["hanoi_12"]["level_call_counts"].items()}
    levels = sorted(lc)
    ax.bar(levels, [lc[k] for k in levels], color=SERIES["dynamic (n-level)"],
           width=0.72, zorder=3)
    ax.set_yscale("log")
    ax.set_xticks(levels)
    tidy(ax, "calls at that layer (log)", "hierarchy layer")
    ax.set_title("hanoi_12: 12 written lines → 8,189 calls → 4,095 moves",
                 fontsize=11, color=INK, loc="left", fontweight="bold", pad=10)
    for k in levels:
        ax.annotate(f"{lc[k]:,}", (k, lc[k]), textcoords="offset points",
                    xytext=(0, 4), ha="center", fontsize=7.4, color=INK2)

    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    framework_figure(HERE / "fig_dynamic_framework.png")
    comparison_figure(HERE / "fig_dynamic_comparison.png")
    depth_figure(HERE / "fig_dynamic_depth.png")
    print("wrote fig_dynamic_framework.png, fig_dynamic_comparison.png, fig_dynamic_depth.png")
