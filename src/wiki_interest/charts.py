"""Monthly line charts from a run dir (PNG, suitable for the PDF report).

Kinds:
  indexed  metric indexed to its first months (= 100) — the cross-language default
  share    views per million edition views
  raw      raw monthly views (not comparable across editions; shown for context)

Encoding: one y-axis; color follows the language (fixed palette order), line style
follows the topic when both vary; legend always shown for >= 2 series and ends of
lines are direct-labeled in neutral ink when there are <= 4 series.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from .engine import load_run  # noqa: E402
from .errors import WikiInterestError  # noqa: E402
from .series import auto_base_months, indexed  # noqa: E402

# Reference categorical palette (light), fixed order — never cycled.
PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
STYLES = ["-", "--", ":", "-."]
INK = "#0b0b0b"
INK_2 = "#52514e"
INK_MUTED = "#8a8984"
GRID = "#e6e5e0"
SURFACE = "#fcfcfb"
SOURCE = "Source: Wikimedia Pageviews API, agent=user"
MAX_SERIES = 8

KINDS = {
    "indexed": "Interest index",
    "share": "Share of edition views",
    "raw": "Monthly pageviews",
}


def _series_frames(run_dir: Path, result: dict) -> list[tuple[dict, pd.DataFrame]]:
    out = []
    listed = result.get("files", {}).get("series", [])
    for i, (rec, det) in enumerate(zip(result["results"], result["details"])):
        rel = det.get("series_file") or "series/" + Path(listed[i]).name  # older runs
        f = run_dir / rel
        df = pd.read_csv(f, index_col="month", parse_dates=["month"])
        if det["stats"].get("data_from"):
            df = df[df.index >= pd.Timestamp(det["stats"]["data_from"] + "-01")]
        out.append((rec, df))
    return out


def _spread_labels(ys: list[float], min_gap: float) -> list[float]:
    """Nudge end-label y positions apart so they don't collide."""
    order = sorted(range(len(ys)), key=lambda i: ys[i])
    placed = list(ys)
    for k in range(1, len(order)):
        a, b = order[k - 1], order[k]
        if placed[b] - placed[a] < min_gap:
            placed[b] = placed[a] + min_gap
    return placed


def make_chart(
    run_dir: str | Path,
    kind: str = "indexed",
    base_months: int | None = None,
    out: str | Path | None = None,
) -> str:
    """Draw one chart for all series in the run; returns the PNG path (posix)."""
    if kind not in KINDS:
        raise WikiInterestError(
            f"Unknown chart kind '{kind}'.", hint="Use --kind indexed, share or raw."
        )
    run_dir = Path(run_dir)
    result = load_run(run_dir)
    frames = _series_frames(run_dir, result)
    if len(frames) > MAX_SERIES:
        frames = frames[:MAX_SERIES]
    metric = result.get("metric", "share")

    langs = list(dict.fromkeys(r["lang"] for r, _ in frames))
    topics = list(dict.fromkeys(r["topic"] for r, _ in frames))
    color_by_lang = len(langs) > 1 or len(topics) == 1

    fig, ax = plt.subplots(figsize=(7.6, 3.5), dpi=200)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)

    ends = []
    base_used = None
    for rec, df in frames:
        if kind == "indexed":
            col = df["share_per_million"] if metric == "share" else df["views"]
            base_used = auto_base_months(len(col), base_months)
            y = indexed(col, base_used)
        elif kind == "share":
            y = df["share_per_million"]
        else:
            y = df["views"]
        if color_by_lang:
            color = PALETTE[langs.index(rec["lang"]) % len(PALETTE)]
            style = STYLES[topics.index(rec["topic"]) % len(STYLES)]
        else:
            color = PALETTE[topics.index(rec["topic"]) % len(PALETTE)]
            style = "-"
        name = rec["lang"] if len(topics) == 1 else (
            rec["topic"] if len(langs) == 1 else f"{rec['topic']} [{rec['lang']}]"
        )
        ax.plot(y.index, y.values, style, color=color, lw=2, label=name, solid_capstyle="round")
        if len(y.dropna()):
            ends.append((y.index[-1], float(y.dropna().iloc[-1]), name))

    if kind == "indexed":
        ax.axhline(100, color=INK_MUTED, lw=1, ls=(0, (2, 2)), zorder=0)
        ylabel = f"Index, first {base_used} months = 100"
    elif kind == "share":
        ylabel = "Views per million edition views"
    else:
        ylabel = "Views per month"
    ax.set_ylabel(ylabel, color=INK_2, fontsize=8)
    ax.set_ylim(bottom=0)

    # recessive axes and grid
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.tick_params(colors=INK_2, labelsize=7.5, length=0)
    ax.xaxis.set_major_locator(mdates.MonthLocator(bymonth=(1, 7)))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax.yaxis.set_major_formatter(
        matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}" if v >= 10 or v == 0 else f"{v:g}")
    )

    # direct labels at line ends (<= 4 series), neutral ink
    if 1 < len(ends) <= 4:
        lo, hi = ax.get_ylim()
        ys = _spread_labels([e[1] for e in ends], (hi - lo) * 0.06)
        for (x, _, name), yl in zip(ends, ys):
            ax.annotate(
                name, (x, yl), xytext=(6, 0), textcoords="offset points",
                va="center", fontsize=7.5, color=INK_2, annotation_clip=False,
            )
    topic_txt = ", ".join(topics) if len(topics) <= 3 else f"{len(topics)} topics"
    lang_txt = ", ".join(langs)
    basis = ""
    if kind == "indexed":
        basis = " (share of edition views)" if metric == "share" else " (raw views)"
    title = f"{KINDS[kind]}{basis}: {topic_txt} ({lang_txt} Wikipedia)"
    if len(ends) > 1:  # legend in its own row above the plot, never over the data
        handles, labels = ax.get_legend_handles_labels()
        order = sorted(range(len(labels)), key=lambda i: (
            langs.index(frames[i][0]["lang"]), topics.index(frames[i][0]["topic"])))
        ax.legend([handles[i] for i in order], [labels[i] for i in order],
                  frameon=False, fontsize=7.5, labelcolor=INK_2, loc="lower left",
                  bbox_to_anchor=(0, 1.0), ncol=min(4, len(ends)), handlelength=2.4,
                  borderaxespad=0.3)
        n_rows = -(-len(ends) // 4)
        ax.set_title(title, loc="left", fontsize=10, color=INK, pad=8 + 13 * n_rows)
    else:
        ax.set_title(title, loc="left", fontsize=10, color=INK, pad=8)
    p = result["period"]
    fig.text(
        0.01, 0.01,
        f"{SOURCE} · {p['start']} to {p['end']} · generated {date.today():%Y-%m-%d}",
        fontsize=6.5, color=INK_MUTED,
    )
    fig.tight_layout(rect=(0, 0.03, 0.97, 1))

    path = Path(out) if out else run_dir / "charts" / f"{kind}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)
    return path.as_posix()
