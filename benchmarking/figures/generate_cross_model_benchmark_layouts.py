from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from matplotlib.table import Table


OUTPUT_DIR = Path(__file__).resolve().parent

LOW_COLOR = "#c73e65"
MEDIUM_COLOR = "#2f7f9f"
HIGH_COLOR = "#2457a6"
TEXT_COLOR = "#1f2933"
GRID_COLOR = "#aab3bc"


CONDITIONS = [
    ("Closed", "GPT-5.5", "Low", "Reasoning effort", "effort=low"),
    ("Closed", "GPT-5.5", "Medium", "Reasoning effort", "effort=medium"),
    ("Closed", "GPT-5.5", "High", "Reasoning effort", "effort=high"),
    ("Closed", "Claude Fable 5", "Low", "Reasoning effort", "effort=low"),
    ("Closed", "Claude Fable 5", "Medium", "Reasoning effort", "effort=medium"),
    ("Closed", "Claude Fable 5", "High", "Reasoning effort", "effort=high"),
    ("Closed", "Gemini 3.1 Pro Preview", "Low", "Thinking level", "thinking=low"),
    ("Closed", "Gemini 3.1 Pro Preview", "Medium", "Thinking level", "thinking=medium"),
    ("Closed", "Gemini 3.1 Pro Preview", "High", "Thinking level", "thinking=high"),
    ("Open", "Qwen3.5", "Low", "Parameter tier", "2B"),
    ("Open", "Qwen3.5", "Medium", "Parameter tier", "4B"),
    ("Open", "Qwen3.5", "High", "Parameter tier", "9B"),
    ("Open", "Ministral-3-Reasoning", "Low", "Parameter tier", "3B"),
    ("Open", "Ministral-3-Reasoning", "Medium", "Parameter tier", "8B"),
    ("Open", "Ministral-3-Reasoning", "High", "Parameter tier", "14B"),
]


def tier_color(tier: str) -> str:
    return {
        "Low": LOW_COLOR,
        "Medium": MEDIUM_COLOR,
        "High": HIGH_COLOR,
    }[tier]


def build_combined_table() -> Path:
    columns = [
        "Source",
        "Model family",
        "Tier",
        "Tier mechanism",
        "Configuration",
        *[f"H{n}" for n in range(3, 13)],
        "Mean",
    ]
    rows = [
        [source, family, tier, mechanism, config, *(["TBD"] * 10), "TBD"]
        for source, family, tier, mechanism, config in CONDITIONS
    ]

    fig = plt.figure(figsize=(24, 13.5), dpi=160, facecolor="white")
    ax = fig.add_axes([0.025, 0.16, 0.95, 0.72])
    ax.axis("off")

    fig.text(
        0.5,
        0.955,
        "Table 1. Planned Closed- and Open-Source Hanoi Benchmark Matrix",
        ha="center",
        va="top",
        fontsize=24,
        fontweight="bold",
        color=TEXT_COLOR,
    )
    fig.text(
        0.5,
        0.915,
        "Full H1/H2 hierarchy + Inner/Outer for every condition | Hanoi 3-12 | 25 independent runs per cell",
        ha="center",
        va="top",
        fontsize=14,
        color="#45525f",
    )
    fig.text(
        0.5,
        0.887,
        "Each result cell should be reported as success % (successful runs / 25), for example 80% (20/25).",
        ha="center",
        va="top",
        fontsize=12,
        color="#596775",
    )

    widths = [0.055, 0.145, 0.06, 0.105, 0.09] + [0.047] * 10 + [0.06]
    heights = [0.06] + [0.052] * len(rows)
    table = Table(ax, bbox=[0, 0, 1, 1])

    for col_idx, (column, width) in enumerate(zip(columns, widths)):
        cell = table.add_cell(
            0,
            col_idx,
            width=width,
            height=heights[0],
            text=column,
            loc="center",
            facecolor="#263746",
            edgecolor="white",
        )
        cell.get_text().set_color("white")
        cell.get_text().set_fontsize(9.5)
        cell.get_text().set_fontweight("bold")

    for row_idx, row in enumerate(rows, start=1):
        source, _, tier, _, _ = CONDITIONS[row_idx - 1]
        group_color = "#e8f0f7" if source == "Closed" else "#e9f3e7"
        for col_idx, (value, width) in enumerate(zip(row, widths)):
            facecolor = group_color if col_idx < 5 else "#f8fafb"
            if col_idx == 2:
                facecolor = tier_color(tier)
            if row_idx in {4, 7, 10, 13}:
                top_edge = "#4e5d69"
            else:
                top_edge = GRID_COLOR
            cell = table.add_cell(
                row_idx,
                col_idx,
                width=width,
                height=heights[row_idx],
                text=value,
                loc="center",
                facecolor=facecolor,
                edgecolor=top_edge,
            )
            cell.set_linewidth(1.3 if row_idx in {4, 7, 10, 13} else 0.7)
            cell.get_text().set_fontsize(8.7)
            cell.get_text().set_color("white" if col_idx == 2 else TEXT_COLOR)
            if col_idx in {0, 1, 2}:
                cell.get_text().set_fontweight("bold")

    ax.add_table(table)

    note_y = 0.125
    fig.patches.append(
        Rectangle(
            (0.035, 0.035),
            0.93,
            0.09,
            transform=fig.transFigure,
            facecolor="#f4f6f8",
            edgecolor="#c6ced5",
            linewidth=1.0,
        )
    )
    fig.text(
        0.055,
        note_y - 0.012,
        "Design notes",
        fontsize=11,
        fontweight="bold",
        color=TEXT_COLOR,
        va="top",
    )
    fig.text(
        0.13,
        note_y - 0.012,
        "Closed-source tiers are inference-time reasoning controls. Open-source tiers are different parameter sizes and are capacity proxies, not the same intervention.\n"
        "Primary metric: legal goal completion. Report optimality, tokens, runtime, replans, and H1/H2 counts separately or in an appendix.\n"
        "Total final trials: 15 conditions x 10 Hanoi sizes x 25 repetitions = 3,750 model-task trials.",
        fontsize=10.5,
        color="#3f4c58",
        va="top",
        linespacing=1.45,
    )

    output = OUTPUT_DIR / "table_cross_model_hanoi_3_to_12_layout.png"
    fig.savefig(output, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return output


def configure_panel(ax: plt.Axes, title: str, subtitle: str) -> None:
    ax.set_xlim(2.7, 12.3)
    ax.set_ylim(0, 103)
    ax.set_xticks(range(3, 13))
    ax.set_yticks(range(0, 101, 20))
    ax.grid(True, color="#d8dee4", linewidth=0.7)
    ax.set_title(title, fontsize=13, fontweight="bold", color=TEXT_COLOR, pad=18)
    ax.text(
        0.5,
        1.015,
        subtitle,
        transform=ax.transAxes,
        ha="center",
        va="bottom",
        fontsize=9,
        color="#5b6874",
    )
    ax.text(
        0.5,
        0.48,
        "Populate with mean success\nand 95% confidence interval",
        transform=ax.transAxes,
        ha="center",
        va="center",
        fontsize=10,
        color="#9aa4ad",
    )
    for spine in ax.spines.values():
        spine.set_color("#7f8b95")
    ax.tick_params(labelsize=8.5)


def build_small_multiples() -> Path:
    fig, axes = plt.subplots(2, 3, figsize=(18, 10), dpi=160, sharex=True, sharey=True)
    fig.patch.set_facecolor("white")
    fig.suptitle(
        "Alternative Figure: Hanoi Scaling Curves by Model Family",
        fontsize=22,
        fontweight="bold",
        color=TEXT_COLOR,
        y=0.985,
    )
    fig.text(
        0.5,
        0.947,
        "One panel per family avoids an unreadable 15-line plot. Use the same axes and success definition in every panel.",
        ha="center",
        fontsize=12,
        color="#53616d",
    )

    panel_specs = [
        ("GPT-5.5", "Reasoning effort: low / medium / high"),
        ("Claude Fable 5", "Reasoning effort: low / medium / high"),
        ("Gemini 3.1 Pro Preview", "Thinking level: low / medium / high"),
        ("Qwen3.5", "Parameter tiers: 2B / 4B / 9B"),
        ("Ministral-3-Reasoning", "Parameter tiers: 3B / 8B / 14B"),
    ]
    for ax, (title, subtitle) in zip(axes.flat[:5], panel_specs):
        configure_panel(ax, title, subtitle)
        ax.plot([], [], color=LOW_COLOR, marker="o", linewidth=2.0, label="Low")
        ax.plot([], [], color=MEDIUM_COLOR, marker="s", linewidth=2.0, label="Medium")
        ax.plot([], [], color=HIGH_COLOR, marker="^", linewidth=2.2, label="High")
        ax.legend(loc="lower left", fontsize=8, frameon=True, ncol=3)

    info_ax = axes.flat[5]
    info_ax.axis("off")
    info_ax.add_patch(
        Rectangle(
            (0.08, 0.12),
            0.84,
            0.76,
            transform=info_ax.transAxes,
            facecolor="#f4f6f8",
            edgecolor="#c5cdd4",
        )
    )
    info_ax.text(
        0.5,
        0.76,
        "Recommended reporting",
        transform=info_ax.transAxes,
        ha="center",
        fontsize=13,
        fontweight="bold",
        color=TEXT_COLOR,
    )
    info_ax.text(
        0.15,
        0.66,
        "x-axis: Hanoi disks (3-12)\n"
        "y-axis: mean success (%)\n"
        "line: Low / Medium / High tier\n"
        "band: 95% confidence interval\n"
        "samples: 25 runs per point\n\n"
        "Keep the framework fixed to full\n"
        "H1/H2 + Inner/Outer for this figure.",
        transform=info_ax.transAxes,
        ha="left",
        va="top",
        fontsize=11,
        color="#42505c",
        linespacing=1.45,
    )

    for ax in axes[:, 0]:
        ax.set_ylabel("Success (%)", fontsize=11)
    for ax in axes[1, :2]:
        ax.set_xlabel("Complexity (number of disks)", fontsize=11)

    fig.subplots_adjust(left=0.055, right=0.98, bottom=0.08, top=0.88, wspace=0.16, hspace=0.28)
    output = OUTPUT_DIR / "figure_cross_model_hanoi_small_multiples_layout.png"
    fig.savefig(output, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return output


def main() -> None:
    print(build_combined_table())
    print(build_small_multiples())


if __name__ == "__main__":
    main()
