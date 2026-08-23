from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

from generate_cross_model_benchmark_layouts import (
    HIGH_COLOR,
    LOW_COLOR,
    MEDIUM_COLOR,
    TEXT_COLOR,
)


OUTPUT_DIR = Path(__file__).resolve().parent
TIER_STYLES = {
    "Low": (LOW_COLOR, "o"),
    "Medium": (MEDIUM_COLOR, "s"),
    "High": (HIGH_COLOR, "^"),
}


def configure_axis(ax: plt.Axes, title: str, subtitle: str) -> None:
    ax.set_xlim(2.7, 12.3)
    ax.set_ylim(0, 103)
    ax.set_xticks(range(3, 13))
    ax.set_yticks(range(0, 101, 20))
    ax.grid(True, color="#d7dde3", linewidth=0.75)
    ax.axhline(50, color="#8a949d", linestyle="--", linewidth=1.1)
    ax.set_title(title, fontsize=15, fontweight="bold", color=TEXT_COLOR, pad=21)
    ax.text(
        0.5,
        1.015,
        subtitle,
        transform=ax.transAxes,
        ha="center",
        va="bottom",
        fontsize=9.5,
        color="#5c6974",
    )
    ax.set_xlabel("Complexity (number of disks)", fontsize=11)
    ax.tick_params(labelsize=9)
    for spine in ax.spines.values():
        spine.set_color("#7f8b95")


def add_tier_legend(ax: plt.Axes, location: str = "lower left") -> None:
    handles = [
        Line2D(
            [0],
            [0],
            color=color,
            marker=marker,
            linewidth=2.5,
            label=tier,
        )
        for tier, (color, marker) in TIER_STYLES.items()
    ]
    ax.legend(handles=handles, loc=location, ncol=3, fontsize=9, frameon=True)


def build_source_group_means() -> Path:
    fig, axes = plt.subplots(1, 2, figsize=(14, 6), dpi=160, sharex=True, sharey=True)
    fig.patch.set_facecolor("white")
    fig.suptitle(
        "Alternative: Mean Success by Source Group and Tier",
        fontsize=21,
        fontweight="bold",
        color=TEXT_COLOR,
        y=0.985,
    )
    fig.text(
        0.5,
        0.925,
        "Three tier lines per panel; compute an equal-weight mean across model families at every disk count.",
        ha="center",
        fontsize=11,
        color="#596671",
    )

    configure_axis(
        axes[0],
        "Closed Source",
        "Mean of GPT-5.5, Claude Fable 5, and Gemini 3.1 Pro Preview",
    )
    configure_axis(
        axes[1],
        "Open Source",
        "Mean of Qwen3.5 and Ministral-3-Reasoning",
    )
    axes[0].set_ylabel("Mean success (%)", fontsize=11)
    for ax in axes:
        add_tier_legend(ax)
        ax.text(
            0.5,
            0.48,
            "Populate with Low / Medium / High\ngroup means after benchmarking",
            transform=ax.transAxes,
            ha="center",
            va="center",
            fontsize=10,
            color="#9ca6ae",
        )

    fig.text(
        0.5,
        0.035,
        "Use thin, low-opacity model-family traces behind each mean line so the aggregate does not hide model disagreement.",
        ha="center",
        fontsize=10,
        color="#5b6874",
    )
    fig.subplots_adjust(left=0.075, right=0.98, bottom=0.13, top=0.82, wspace=0.12)
    output = OUTPUT_DIR / "figure_closed_open_source_mean_tiers_layout.png"
    fig.savefig(output, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return output


def model_tier_handles(models: list[tuple[str, str]]) -> list[Line2D]:
    handles: list[Line2D] = []
    for model, linestyle in models:
        for tier, (color, marker) in TIER_STYLES.items():
            handles.append(
                Line2D(
                    [0],
                    [0],
                    color=color,
                    linestyle=linestyle,
                    marker=marker,
                    linewidth=2.1,
                    label=f"{model} - {tier}",
                )
            )
    return handles


def build_combined_model_figure(
    source: str,
    models: list[tuple[str, str]],
    title: str,
    subtitle: str,
    filename: str,
) -> Path:
    figure_width = 14 if source == "Open" else 17
    fig, ax = plt.subplots(figsize=(figure_width, 7), dpi=160)
    fig.patch.set_facecolor("white")
    configure_axis(ax, title, subtitle)
    ax.set_ylabel("Success (%)", fontsize=11)
    ax.text(
        0.5,
        0.5,
        "Populate with benchmark success curves",
        transform=ax.transAxes,
        ha="center",
        va="center",
        fontsize=11,
        color="#9ca6ae",
    )

    handles = model_tier_handles(models)
    legend_columns = 3 if source == "Open" else 3
    ax.legend(
        handles=handles,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.15),
        ncol=legend_columns,
        fontsize=9,
        frameon=True,
    )
    fig.text(
        0.5,
        0.025,
        "Encoding: color = Low/Medium/High tier; line style = model family; marker = tier.",
        ha="center",
        fontsize=10,
        color="#5a6772",
    )
    fig.subplots_adjust(left=0.075, right=0.98, bottom=0.27, top=0.84)
    output = OUTPUT_DIR / filename
    fig.savefig(output, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return output


def main() -> None:
    print(build_source_group_means())
    print(
        build_combined_model_figure(
            source="Open",
            models=[("Qwen3.5", "-"), ("Ministral-3-Reasoning", "--")],
            title="Open-Source Models: All Capacity Tiers on One Graph",
            subtitle="Qwen3.5: 2B / 4B / 9B | Ministral-3-Reasoning: 3B / 8B / 14B",
            filename="figure_open_source_two_models_all_tiers_layout.png",
        )
    )
    print(
        build_combined_model_figure(
            source="Closed",
            models=[
                ("GPT-5.5", "-"),
                ("Claude Fable 5", "--"),
                ("Gemini 3.1 Pro", ":"),
            ],
            title="Closed-Source Models: All Reasoning Tiers on One Graph",
            subtitle="Three models x Low/Medium/High reasoning = nine curves",
            filename="figure_closed_source_three_models_all_tiers_layout.png",
        )
    )


if __name__ == "__main__":
    main()
