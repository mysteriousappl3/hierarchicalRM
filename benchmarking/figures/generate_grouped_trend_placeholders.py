from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt

from generate_cross_model_benchmark_layouts import (
    HIGH_COLOR,
    LOW_COLOR,
    MEDIUM_COLOR,
    TEXT_COLOR,
)


OUTPUT_DIR = Path(__file__).resolve().parent
DISKS = list(range(3, 13))
TIER_COLORS = {
    "Low": LOW_COLOR,
    "Medium": MEDIUM_COLOR,
    "High": HIGH_COLOR,
}
TIER_MARKERS = {
    "Low": "o",
    "Medium": "s",
    "High": "^",
}


CLOSED_PLACEHOLDER = {
    ("GPT-5.5", "Low"): [100, 100, 100, 96, 88, 72, 52, 32, 12, 0],
    ("GPT-5.5", "Medium"): [100, 100, 100, 100, 96, 88, 76, 56, 32, 12],
    ("GPT-5.5", "High"): [100, 100, 100, 100, 100, 96, 88, 72, 52, 28],
    ("Claude Fable 5", "Low"): [100, 100, 96, 92, 84, 68, 48, 28, 8, 0],
    ("Claude Fable 5", "Medium"): [100, 100, 100, 100, 96, 88, 72, 52, 28, 8],
    ("Claude Fable 5", "High"): [100, 100, 100, 100, 100, 96, 84, 68, 44, 20],
    ("Gemini 3.1 Pro", "Low"): [100, 100, 96, 92, 80, 64, 44, 24, 8, 0],
    ("Gemini 3.1 Pro", "Medium"): [100, 100, 100, 96, 92, 84, 68, 48, 24, 8],
    ("Gemini 3.1 Pro", "High"): [100, 100, 100, 100, 96, 92, 80, 64, 40, 16],
}


OPEN_PLACEHOLDER = {
    ("Qwen3.5", "Low"): [100, 96, 84, 68, 44, 24, 8, 0, 0, 0],
    ("Qwen3.5", "Medium"): [100, 100, 96, 88, 72, 52, 32, 12, 4, 0],
    ("Qwen3.5", "High"): [100, 100, 100, 96, 88, 76, 56, 36, 16, 4],
    ("Ministral-3-Reasoning", "Low"): [100, 96, 88, 72, 48, 28, 12, 4, 0, 0],
    ("Ministral-3-Reasoning", "Medium"): [100, 100, 96, 88, 76, 56, 36, 16, 4, 0],
    ("Ministral-3-Reasoning", "High"): [100, 100, 100, 96, 92, 80, 64, 44, 24, 8],
}


def render_placeholder(
    data: dict[tuple[str, str], list[int]],
    model_styles: dict[str, str],
    title: str,
    subtitle: str,
    filename: str,
    width: float,
) -> Path:
    fig, ax = plt.subplots(figsize=(width, 7.2), dpi=160)
    fig.patch.set_facecolor("white")

    for (model, tier), values in data.items():
        ax.plot(
            DISKS,
            values,
            color=TIER_COLORS[tier],
            linestyle=model_styles[model],
            marker=TIER_MARKERS[tier],
            markersize=5.2,
            linewidth=2.1,
            markerfacecolor="white",
            markeredgewidth=1.2,
            label=f"{model} - {tier}",
        )

    ax.axhline(50, color="#7c8790", linestyle="--", linewidth=1.1, alpha=0.9)
    ax.text(12.17, 51.5, "50%", ha="right", va="bottom", fontsize=9, color="#65717b")
    ax.set_xlim(2.7, 12.3)
    ax.set_ylim(-2, 104)
    ax.set_xticks(DISKS)
    ax.set_yticks(range(0, 101, 20))
    ax.set_xlabel("Complexity (number of disks)", fontsize=12)
    ax.set_ylabel("Success (%)", fontsize=12)
    ax.grid(True, color="#d8dee4", linewidth=0.7)
    for spine in ax.spines.values():
        spine.set_color("#75818b")
    ax.tick_params(labelsize=9.5)

    fig.suptitle(title, fontsize=21, fontweight="bold", color=TEXT_COLOR, y=0.985)
    fig.text(0.5, 0.935, subtitle, ha="center", fontsize=11, color="#56636e")
    fig.text(
        0.5,
        0.895,
        "PLACEHOLDER - ILLUSTRATIVE DATA ONLY - NOT BENCHMARK RESULTS",
        ha="center",
        fontsize=11,
        fontweight="bold",
        color="#b43a3a",
    )
    fig.text(
        0.5,
        0.02,
        "Values are illustrative multiples of 4%, matching the resolution of 25 trials per point. "
        "Color = tier; line style = model family.",
        ha="center",
        fontsize=9.5,
        color="#596671",
    )

    ax.legend(
        loc="upper center",
        bbox_to_anchor=(0.5, -0.14),
        ncol=3,
        fontsize=8.5,
        frameon=True,
    )
    fig.subplots_adjust(left=0.075, right=0.98, bottom=0.27, top=0.83)
    output = OUTPUT_DIR / filename
    fig.savefig(output, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return output


def main() -> None:
    print(
        render_placeholder(
            data=CLOSED_PLACEHOLDER,
            model_styles={"GPT-5.5": "-", "Claude Fable 5": "--", "Gemini 3.1 Pro": ":"},
            title="Closed-Source Hanoi Scaling by Reasoning Tier",
            subtitle="GPT-5.5, Claude Fable 5, and Gemini 3.1 Pro with Low / Medium / High reasoning",
            filename="figure_closed_source_all_tiers_placeholder.png",
            width=17,
        )
    )
    print(
        render_placeholder(
            data=OPEN_PLACEHOLDER,
            model_styles={"Qwen3.5": "-", "Ministral-3-Reasoning": "--"},
            title="Open-Source Hanoi Scaling by Capacity Tier",
            subtitle="Qwen3.5 2B / 4B / 9B and Ministral-3-Reasoning 3B / 8B / 14B",
            filename="figure_open_source_all_tiers_placeholder.png",
            width=14,
        )
    )


if __name__ == "__main__":
    main()
