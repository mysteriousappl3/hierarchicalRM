from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from matplotlib.table import Table

from generate_cross_model_benchmark_layouts import (
    CONDITIONS,
    GRID_COLOR,
    HIGH_COLOR,
    LOW_COLOR,
    MEDIUM_COLOR,
    TEXT_COLOR,
    tier_color,
)


OUTPUT_DIR = Path(__file__).resolve().parent


def build_result_table(source: str) -> Path:
    conditions = [condition for condition in CONDITIONS if condition[0] == source]
    source_label = "Closed-Source" if source == "Closed" else "Open-Source"
    columns = [
        "Model family",
        "Tier",
        "Tier mechanism",
        "Configuration",
        *[f"H{n}" for n in range(3, 13)],
        "Mean",
        "Last N >=50%",
    ]
    rows = [
        [family, tier, mechanism, config, *(["TBD"] * 10), "TBD", "TBD"]
        for _, family, tier, mechanism, config in conditions
    ]

    width = 22
    height = 9.3 if source == "Closed" else 7.8
    fig = plt.figure(figsize=(width, height), dpi=160, facecolor="white")
    ax = fig.add_axes([0.025, 0.19, 0.95, 0.65])
    ax.axis("off")

    fig.text(
        0.5,
        0.955,
        f"Table. {source_label} Hanoi Benchmark Results",
        ha="center",
        va="top",
        fontsize=23,
        fontweight="bold",
        color=TEXT_COLOR,
    )
    fig.text(
        0.5,
        0.91,
        "Full H1/H2 hierarchy + Inner/Outer | Hanoi 3-12 | 25 independent runs per cell",
        ha="center",
        va="top",
        fontsize=13,
        color="#4d5b67",
    )
    qualifier = (
        "Low/Medium/High are inference-time reasoning controls."
        if source == "Closed"
        else "Low/Medium/High are parameter-size capacity tiers, not inference-time reasoning controls."
    )
    fig.text(
        0.5,
        0.878,
        qualifier,
        ha="center",
        va="top",
        fontsize=11.5,
        color="#65727d",
    )

    widths = [0.17, 0.065, 0.115, 0.095] + [0.047] * 10 + [0.06, 0.085]
    row_height = 0.072 if source == "Closed" else 0.095
    table = Table(ax, bbox=[0, 0, 1, 1])

    for col_idx, (column, cell_width) in enumerate(zip(columns, widths)):
        cell = table.add_cell(
            0,
            col_idx,
            width=cell_width,
            height=row_height,
            text=column,
            loc="center",
            facecolor="#263746",
            edgecolor="white",
        )
        cell.get_text().set_color("white")
        cell.get_text().set_fontweight("bold")
        cell.get_text().set_fontsize(9.3)

    group_fill = "#e8f0f7" if source == "Closed" else "#e9f3e7"
    group_boundaries = {4, 7} if source == "Closed" else {4}
    for row_idx, row in enumerate(rows, start=1):
        tier = conditions[row_idx - 1][2]
        for col_idx, (value, cell_width) in enumerate(zip(row, widths)):
            if col_idx < 4:
                facecolor = group_fill
            elif col_idx >= 14:
                facecolor = "#edf1f4"
            else:
                facecolor = "#f8fafb"
            if col_idx == 1:
                facecolor = tier_color(tier)
            edgecolor = "#4e5d69" if row_idx in group_boundaries else GRID_COLOR
            cell = table.add_cell(
                row_idx,
                col_idx,
                width=cell_width,
                height=row_height,
                text=value,
                loc="center",
                facecolor=facecolor,
                edgecolor=edgecolor,
            )
            cell.set_linewidth(1.3 if row_idx in group_boundaries else 0.7)
            cell.get_text().set_fontsize(8.8)
            cell.get_text().set_color("white" if col_idx == 1 else TEXT_COLOR)
            if col_idx in {0, 1}:
                cell.get_text().set_fontweight("bold")

    ax.add_table(table)

    fig.patches.append(
        Rectangle(
            (0.035, 0.035),
            0.93,
            0.105,
            transform=fig.transFigure,
            facecolor="#f4f6f8",
            edgecolor="#c6ced5",
        )
    )
    fig.text(0.055, 0.117, "Reading the table", fontsize=11, fontweight="bold", color=TEXT_COLOR)
    fig.text(
        0.145,
        0.119,
        "Report cells as success % (successful runs / 25), e.g. 80% (20/25). "
        "Shade completed cells by success rate: red = 0%, amber = 50%, green = 100%.\n"
        "Mean summarizes all ten Hanoi sizes. Last N >=50% exposes the practical scaling boundary. "
        "Report tokens, runtime, replans, and hierarchy-call counts in an appendix.",
        fontsize=10.5,
        color="#42505c",
        va="top",
        linespacing=1.5,
    )
    legend_x = 0.72
    for offset, color, label in [
        (0.00, "#c94c4c", "0%"),
        (0.07, "#e4b04a", "50%"),
        (0.14, "#4c9a68", "100%"),
    ]:
        fig.patches.append(
            Rectangle(
                (legend_x + offset, 0.052),
                0.025,
                0.022,
                transform=fig.transFigure,
                facecolor=color,
                edgecolor="white",
            )
        )
        fig.text(legend_x + offset + 0.03, 0.052, label, fontsize=9.5, color="#42505c")

    filename = (
        "table_closed_source_hanoi_3_to_12_layout.png"
        if source == "Closed"
        else "table_open_source_hanoi_3_to_12_layout.png"
    )
    output = OUTPUT_DIR / filename
    fig.savefig(output, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return output


def configure_trend_panel(ax: plt.Axes, title: str, subtitle: str) -> None:
    ax.set_xlim(2.7, 12.3)
    ax.set_ylim(0, 103)
    ax.set_xticks(range(3, 13))
    ax.set_yticks(range(0, 101, 20))
    ax.grid(True, color="#d7dde3", linewidth=0.75)
    ax.set_title(title, fontsize=14, fontweight="bold", color=TEXT_COLOR, pad=19)
    ax.text(
        0.5,
        1.015,
        subtitle,
        transform=ax.transAxes,
        ha="center",
        va="bottom",
        fontsize=9.5,
        color="#5d6974",
    )
    ax.text(
        0.5,
        0.48,
        "Mean success +/- 95% CI",
        transform=ax.transAxes,
        ha="center",
        color="#a0a9b1",
        fontsize=10,
    )
    ax.plot([], [], color=LOW_COLOR, marker="o", linewidth=2.2, label="Low")
    ax.plot([], [], color=MEDIUM_COLOR, marker="s", linewidth=2.2, label="Medium")
    ax.plot([], [], color=HIGH_COLOR, marker="^", linewidth=2.4, label="High")
    ax.legend(loc="lower left", ncol=3, fontsize=8.5, frameon=True)
    ax.tick_params(labelsize=9)
    for spine in ax.spines.values():
        spine.set_color("#7f8b95")


def build_trend_figure(source: str) -> Path:
    if source == "Closed":
        panels = [
            ("GPT-5.5", "Reasoning effort"),
            ("Claude Fable 5", "Reasoning effort"),
            ("Gemini 3.1 Pro Preview", "Thinking level"),
        ]
        fig, axes = plt.subplots(1, 3, figsize=(18, 5.8), dpi=160, sharex=True, sharey=True)
        title = "Closed-Source Hanoi Scaling Trends"
        filename = "figure_closed_source_hanoi_trends_layout.png"
    else:
        panels = [
            ("Qwen3.5", "2B / 4B / 9B capacity tiers"),
            ("Ministral-3-Reasoning", "3B / 8B / 14B capacity tiers"),
        ]
        fig, axes = plt.subplots(1, 2, figsize=(13, 5.8), dpi=160, sharex=True, sharey=True)
        title = "Open-Source Hanoi Scaling Trends"
        filename = "figure_open_source_hanoi_trends_layout.png"

    fig.patch.set_facecolor("white")
    fig.suptitle(title, fontsize=21, fontweight="bold", color=TEXT_COLOR, y=0.98)
    fig.text(
        0.5,
        0.92,
        "The first sustained drop below 50% marks the scaling-collapse region.",
        ha="center",
        fontsize=11,
        color="#596671",
    )
    for ax, (panel_title, subtitle) in zip(axes, panels):
        configure_trend_panel(ax, panel_title, subtitle)
        ax.axhline(50, color="#8a949d", linestyle="--", linewidth=1.1)
        ax.set_xlabel("Complexity (number of disks)", fontsize=11)
    axes[0].set_ylabel("Success (%)", fontsize=11)
    fig.subplots_adjust(left=0.065, right=0.98, bottom=0.13, top=0.82, wspace=0.14)
    output = OUTPUT_DIR / filename
    fig.savefig(output, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return output


def main() -> None:
    print(build_result_table("Closed"))
    print(build_result_table("Open"))
    print(build_trend_figure("Closed"))
    print(build_trend_figure("Open"))


if __name__ == "__main__":
    main()
