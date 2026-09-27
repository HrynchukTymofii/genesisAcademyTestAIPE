"""One-page PDF report (reportlab).

Sections: headline answer, main chart, per-language metrics table, recommendation
(the agent's --summary), assumptions and limitations (from warnings), data period
and generation date. Exactly one page is enforced: progressively smaller layouts
are tried, then the content is shrunk to fit.

The summary guard rejects any number in --summary that does not appear in the
run's results, so the model cannot invent statistics.
"""

from __future__ import annotations

import re
from urllib.parse import unquote
from io import BytesIO
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image,
    KeepInFrame,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from xml.sax.saxutils import escape

from . import __version__
from .api import today
from .engine import load_run
from .errors import SummaryGuardError, WikiInterestError

SKILL_DIR = Path(__file__).resolve().parents[2]
FONT_DIR = SKILL_DIR / "assets" / "fonts"
INK = colors.HexColor("#0b0b0b")
INK_2 = colors.HexColor("#52514e")
RULE = colors.HexColor("#e6e5e0")
HEAD_BG = colors.HexColor("#f3f2ee")

# -- i18n -----------------------------------------------------------------------------
T = {
    "en": {
        "sources": "Sources",
        "ranking": "Ranking by your criteria",
        "note": "Trend verdicts use share of edition views (views per million), which removes changes in each edition's overall traffic.",
        "title": "Wikipedia interest report",
        "headline": "Answer",
        "table": "Metrics per series",
        "rec": "Recommendation",
        "limits": "Assumptions and limitations",
        "cols": ["Topic", "Lang", "Verdict", "Trend %/yr (95% CI)", "YoY %", "Views /day", "Share /M", "Confidence"],
        "verdict": {"growing": "growing", "declining": "declining", "stable": "stable", "unclear": "unclear", "unknown": "unknown"},
        "conf": {"strong": "strong", "moderate": "moderate", "weak": "weak", "insufficient_data": "insufficient data"},
        "hl": "{who}: {verdict} {pct}%/yr (95% CI {lo}..{hi}); confidence: {conf}",
        "hl_insuf": "{who}: insufficient data",
        "period": "Data period {start} to {end} ({months} complete months). Generated {today}.",
        "std": [
            "Trends use share of edition views (views per million), so changes in a Wikipedia edition's total traffic do not create fake growth; raw views are shown for context.",
            "Pageviews signal interest and curiosity, not purchase intent or willingness to pay.",
            "agent=user excludes identified bots; some automated traffic may remain. Article renames are handled by merging redirects.",
        ],
        "std_raw": "Trends use raw views; they include changes in each edition's total traffic.",
        "missing": "Not analysed: ",
    },
    "uk": {
        "sources": "Джерела",
        "ranking": "Рейтинг за вашими критеріями",
        "note": "Висновки про тренд базуються на частці переглядів мовного розділу (на мільйон), що усуває вплив змін загального трафіку розділу.",
        "title": "Звіт про інтерес у Вікіпедії",
        "headline": "Відповідь",
        "table": "Показники за рядами",
        "rec": "Рекомендація",
        "limits": "Припущення та обмеження",
        "cols": ["Тема", "Мова", "Висновок", "Тренд %/рік (95% ДІ)", "Р/р %", "Перегл. /день", "Частка /млн", "Довіра"],
        "verdict": {"growing": "зростає", "declining": "спадає", "stable": "стабільно", "unclear": "неясно", "unknown": "невідомо"},
        "conf": {"strong": "висока (strong)", "moderate": "помірна (moderate)", "weak": "низька (weak)", "insufficient_data": "замало даних (insufficient_data)"},
        "hl": "{who}: {verdict} {pct}%/рік (95% ДІ {lo}..{hi}); довіра: {conf}",
        "hl_insuf": "{who}: замало даних",
        "period": "Період даних {start} – {end} ({months} повних місяців). Згенеровано {today}.",
        "std": [
            "Тренди рахуються за часткою переглядів мовного розділу (перегляди на мільйон), тож зміни загального трафіку розділу не створюють хибного зростання; сирі перегляди наведено для контексту.",
            "Перегляди сторінок свідчать про інтерес, а не про готовність платити.",
            "agent=user виключає відомих ботів; частина автоматизованого трафіку може лишатися. Перейменування статей враховано через об'єднання перенаправлень.",
        ],
        "std_raw": "Тренди рахуються за сирими переглядами й включають зміни загального трафіку розділу.",
        "missing": "Не проаналізовано: ",
    },
    "pl": {
        "sources": "Źródła",
        "ranking": "Ranking według Twoich kryteriów",
        "note": "Werdykty trendu opierają się na udziale w wyświetleniach edycji (na milion), co usuwa wpływ zmian całego ruchu edycji.",
        "title": "Raport zainteresowania w Wikipedii",
        "headline": "Odpowiedź",
        "table": "Wskaźniki dla serii",
        "rec": "Rekomendacja",
        "limits": "Założenia i ograniczenia",
        "cols": ["Temat", "Język", "Werdykt", "Trend %/rok (95% PU)", "R/R %", "Wyśw./dzień", "Udział /mln", "Pewność"],
        "verdict": {"growing": "rośnie", "declining": "spada", "stable": "stabilnie", "unclear": "niejasno", "unknown": "nieznany"},
        "conf": {"strong": "wysoka (strong)", "moderate": "umiarkowana (moderate)", "weak": "niska (weak)", "insufficient_data": "za mało danych (insufficient_data)"},
        "hl": "{who}: {verdict} {pct}%/rok (95% PU {lo}..{hi}); pewność: {conf}",
        "hl_insuf": "{who}: za mało danych",
        "period": "Okres danych {start} – {end} ({months} pełnych miesięcy). Wygenerowano {today}.",
        "std": [
            "Trendy liczone są na udziale w wyświetleniach danej edycji (na milion), więc zmiany całego ruchu edycji nie tworzą fałszywego wzrostu; surowe wyświetlenia podano dla kontekstu.",
            "Wyświetlenia stron sygnalizują zainteresowanie, a nie gotowość do zapłaty.",
            "agent=user wyklucza znane boty; część ruchu automatycznego może pozostać. Zmiany nazw artykułów obsłużono przez sumowanie przekierowań.",
        ],
        "std_raw": "Trendy liczone są na surowych wyświetleniach i obejmują zmiany ruchu całej edycji.",
        "missing": "Nie przeanalizowano: ",
    },
    "cs": {
        "sources": "Zdroje",
        "ranking": "Pořadí podle vašich kritérií",
        "note": "Verdikty trendu vycházejí z podílu na zobrazeních jazykové verze (na milion), což odstraňuje vliv změn celkového provozu verze.",
        "title": "Zpráva o zájmu na Wikipedii",
        "headline": "Odpověď",
        "table": "Ukazatele podle řad",
        "rec": "Doporučení",
        "limits": "Předpoklady a omezení",
        "cols": ["Téma", "Jazyk", "Verdikt", "Trend %/rok (95% IS)", "Mezirok %", "Zobr./den", "Podíl /mil", "Jistota"],
        "verdict": {"growing": "roste", "declining": "klesá", "stable": "stabilní", "unclear": "nejasné", "unknown": "neznámé"},
        "conf": {"strong": "vysoká (strong)", "moderate": "střední (moderate)", "weak": "nízká (weak)", "insufficient_data": "málo dat (insufficient_data)"},
        "hl": "{who}: {verdict} {pct} %/rok (95% IS {lo}..{hi}); jistota: {conf}",
        "hl_insuf": "{who}: málo dat",
        "period": "Období dat {start} – {end} ({months} celých měsíců). Vygenerováno {today}.",
        "std": [
            "Trendy se počítají z podílu na zobrazeních dané jazykové verze (na milion), takže změny celkového provozu verze nevytvářejí falešný růst; surová zobrazení jsou uvedena pro kontext.",
            "Zobrazení stránek signalizují zájem, ne ochotu platit.",
            "agent=user vylučuje známé boty; část automatizovaného provozu může zůstat. Přejmenování článků je ošetřeno sečtením přesměrování.",
        ],
        "std_raw": "Trendy se počítají ze surových zobrazení a zahrnují změny celkového provozu verze.",
        "missing": "Neanalyzováno: ",
    },
}

LAYOUTS = [  # font size, chart height (mm), max table rows, max limitation bullets
    (9.0, 80, 12, 8),
    (8.5, 68, 10, 6),
    (8.0, 58, 8, 5),
    (7.5, 48, 8, 4),
]


# -- fonts ----------------------------------------------------------------------------
def _font_file(name: str) -> Path:
    bundled = FONT_DIR / name
    if bundled.exists():
        return bundled
    import matplotlib

    return Path(matplotlib.get_data_path()) / "fonts" / "ttf" / name


def register_fonts() -> tuple[str, str]:
    """DejaVu Sans covers Latin, Cyrillic, Greek; returns (regular, bold) names."""
    if "WI-Sans" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("WI-Sans", str(_font_file("DejaVuSans.ttf"))))
        pdfmetrics.registerFont(TTFont("WI-Sans-Bold", str(_font_file("DejaVuSans-Bold.ttf"))))
    return "WI-Sans", "WI-Sans-Bold"


# -- summary number guard ------------------------------------------------------------
NUM_RE = re.compile(r"(?<![\w.])[-+−–]?(?:\d{1,3}(?:[  ]\d{3})+(?!\d)|\d+)(?:[.,]\d+)*")


def _parse_candidates(token: str) -> list[float]:
    """A number as written may be '12,3' (decimal comma), '1,234' or '1 234' (thousands)."""
    t = token.replace("−", "-").replace("–", "-").replace(" ", " ").strip()
    t = t.lstrip("+-")
    out = []
    for variant in {t.replace(" ", ""), t.split(" ")[-1]}:
        if re.fullmatch(r"\d+", variant):
            out.append(float(variant))
        elif re.fullmatch(r"\d+[.,]\d+", variant):
            out.append(float(variant.replace(",", ".")))
            if re.fullmatch(r"\d{1,3}[.,]\d{3}", variant):
                out.append(float(variant.replace(",", "").replace(".", "")))
        elif re.fullmatch(r"\d{1,3}([,.]\d{3})+", variant):
            out.append(float(re.sub(r"[,.]", "", variant)))
    return out


URL_RE = re.compile(r"https?://\S+")
SUMMARY_KEYS = ("period", "headline", "results", "comparisons", "missing", "topics")


def allowed_numbers(result: dict) -> set[float]:
    vals: set[float] = set()

    def walk(o):
        if isinstance(o, bool) or o is None:
            return
        if isinstance(o, (int, float)):
            vals.add(abs(float(o)))
        elif isinstance(o, str):
            for tok in NUM_RE.findall(URL_RE.sub(" ", o)):
                vals.update(_parse_candidates(tok))
        elif isinstance(o, dict):
            for k, v in o.items():
                if k != "sources":  # links and dates are not statistics
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    # Only what the model was shown: the compact summary, not full-precision details,
    # file paths, timestamps or request counters (they would allow almost any number).
    walk({k: v for k, v in result.items() if k in SUMMARY_KEYS})
    months = result.get("period", {}).get("months", 0)
    vals.update({95.0, 100.0, 12.0, float(months), round(months / 12, 1)})
    vals.update(float(x) for x in range(1, len(result.get("results", [])) + 2))
    return vals


def check_summary_numbers(result: dict, summary: str) -> list[str]:
    """Return the numbers in ``summary`` that are not supported by the run results."""
    allowed = allowed_numbers(result)
    bad = []
    for tok in NUM_RE.findall(summary):
        cands = _parse_candidates(tok)
        if not cands:
            continue
        ok = any(
            abs(c - a) <= 0.051 + 1e-9 or (c == round(c) and abs(c - round(a)) < 1e-9 and a >= 1)
            for c in cands
            for a in allowed
        )
        if not ok:
            bad.append(tok.strip())
    return bad


# -- building --------------------------------------------------------------------------
def _fmt(x, nd=1, sign=True) -> str:
    if x is None:
        return "–"
    return f"{x:+.{nd}f}" if sign else f"{x:,.{nd}f}".replace(",", " ")


def _headlines(result: dict, tr: dict) -> list[str]:
    out = []
    for r in result["results"]:
        who = f"{r['topic']} [{r['lang']}]"
        if r["confidence"] == "insufficient_data":
            out.append(tr["hl_insuf"].format(who=who))
            continue
        lo, hi = r["trend_ci95"]
        out.append(
            tr["hl"].format(
                who=who,
                verdict=tr["verdict"].get(r["verdict"], r["verdict"]),
                pct=_fmt(r["trend_pct_per_year"]),
                lo=_fmt(lo),
                hi=_fmt(hi),
                conf=tr["conf"].get(r["confidence"], r["confidence"]),
            )
        )
    return out


AI_SHIFT = {
    "en": "Part of Wikipedia's audience has moved to AI assistants and search answers, unevenly by topic (factual and school topics more). Share corrects the edition-wide drop but not these topic differences, so a falling share can mean fewer lookups on Wikipedia rather than less interest; comparing options is more reliable than reading absolute declines.",
    "uk": "Частина аудиторії Вікіпедії перейшла до AI-асистентів і відповідей пошуковиків, нерівномірно за темами (фактичні й шкільні теми — більше). Частка враховує загальне падіння розділу, але не ці відмінності між темами, тож спад частки може означати менше пошуків у Вікіпедії, а не менший інтерес; порівняння варіантів надійніше за абсолютні спади.",
    "pl": "Część czytelników Wikipedii przeszła do asystentów AI i odpowiedzi wyszukiwarek, nierównomiernie według tematów (tematy faktograficzne i szkolne bardziej). Udział koryguje ogólny spadek edycji, ale nie te różnice, więc spadek udziału może oznaczać mniej wyszukiwań w Wikipedii, a nie mniejsze zainteresowanie; porównywanie opcji jest bardziej wiarygodne niż bezwzględne spadki.",
    "cs": "Část čtenářů Wikipedie přešla k AI asistentům a odpovědím vyhledávačů, nerovnoměrně podle témat (faktická a školní témata více). Podíl koriguje celkový pokles verze, ale ne tyto rozdíly, takže pokles podílu může znamenat méně vyhledávání na Wikipedii, ne menší zájem; porovnání možností je spolehlivější než absolutní poklesy.",
}


def _limitations(result: dict, tr: dict, lang: str = "en") -> list[str]:
    items = list(tr["std"]) if result.get("metric", "share") == "share" else [tr["std_raw"], *tr["std"][1:]]
    items.insert(1, AI_SHIFT.get(lang, AI_SHIFT["en"]))
    seen = set()
    for r in result["results"]:
        for w in r.get("warnings", []):
            key = (r["topic"], w)
            if key not in seen:
                seen.add(key)
                items.append(f"{r['topic']} [{r['lang']}]: {w}")
    for m in result.get("missing", []):
        msg = m["message"] if isinstance(m, dict) else str(m)
        items.append(tr["missing"] + msg)
    return items


def _story(result, summary, tr, chart_path, layout, fonts, lang="en"):
    size, chart_h, max_rows, max_limits = layout
    reg, bold = fonts
    st = {
        "title": ParagraphStyle("t", fontName=bold, fontSize=size + 5, leading=size + 8, textColor=INK),
        "sub": ParagraphStyle("s", fontName=reg, fontSize=size - 1, leading=size + 1.5, textColor=INK_2),
        "h": ParagraphStyle("h", fontName=bold, fontSize=size + 1.5, leading=size + 4, textColor=INK, spaceBefore=5, spaceAfter=2),
        "p": ParagraphStyle("p", fontName=reg, fontSize=size, leading=size + 3, textColor=INK, alignment=TA_LEFT),
        "li": ParagraphStyle("li", fontName=reg, fontSize=size - 0.5, leading=size + 2, textColor=INK, leftIndent=8, bulletIndent=0),
        "cell": ParagraphStyle("c", fontName=reg, fontSize=size - 1, leading=size + 1, textColor=INK),
        "cellh": ParagraphStyle("ch", fontName=bold, fontSize=size - 1, leading=size + 1, textColor=INK),
    }
    truncated = []
    topics = list(dict.fromkeys(r["topic"] for r in result["results"]))
    langs = list(dict.fromkeys(r["lang"] for r in result["results"]))
    story = [
        Paragraph(escape(f"{tr['title']}: {', '.join(topics)} ({', '.join(langs)})"), st["title"]),
        Spacer(1, 2),
        Paragraph(escape(tr["note"] if result.get("metric", "share") == "share" else tr["std_raw"]), st["sub"]),
        Paragraph(escape(tr["headline"]), st["h"]),
    ]
    hls = _headlines(result, tr)
    if len(hls) > max_rows:
        truncated.append(f"headline lines {len(hls)} -> {max_rows}")
        hls = hls[:max_rows]
    story += [Paragraph(escape(h), st["li"], bulletText="•") for h in hls]

    if chart_path and Path(chart_path).exists():
        w = 180 * mm
        story += [Spacer(1, 4), Image(str(chart_path), width=w, height=chart_h * mm * (w / (180 * mm)), kind="proportional")]

    story.append(Paragraph(escape(tr["table"]), st["h"]))
    rows = result["results"]
    if len(rows) > max_rows:
        truncated.append(f"table rows {len(rows)} -> {max_rows}")
        rows = rows[:max_rows]
    data = [[Paragraph(escape(c), st["cellh"]) for c in tr["cols"]]]
    for r in rows:
        lo, hi = r["trend_ci95"]
        trend = "–" if r["trend_pct_per_year"] is None else f"{_fmt(r['trend_pct_per_year'])} ({_fmt(lo)}..{_fmt(hi)})"
        data.append(
            [
                Paragraph(escape(r["topic"]), st["cell"]),
                r["lang"],
                tr["verdict"].get(r["verdict"], r["verdict"]),
                trend,
                _fmt(r.get("yoy_pct")),
                _fmt(r.get("median_daily_views"), 0, sign=False),
                "–" if r.get("share_per_million_last12") is None else f"{r['share_per_million_last12']:.2f}",
                Paragraph(escape(tr["conf"].get(r["confidence"], r["confidence"])), st["cell"]),
            ]
        )
    widths = [x * mm for x in (27, 14, 22, 36, 15, 20, 17, 29)]
    table = Table(data, colWidths=widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 1), (-1, -1), reg),
                ("FONTSIZE", (0, 1), (-1, -1), size - 1),
                ("TEXTCOLOR", (0, 0), (-1, -1), INK),
                ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
                ("LINEBELOW", (0, 0), (-1, -1), 0.4, RULE),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (3, 1), (6, -1), "RIGHT"),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    story.append(table)

    cr = result.get("comparisons", {}).get("custom_ranking")
    if cr and cr.get("ranked"):
        weights = ", ".join(f"{c} {w * 100:.0f}%" for c, w in cr["weights"].items())
        items = [
            f"{r['rank']}. {r['topic']} [{r['lang']}]: {r['score']:.1f}"
            for r in cr["ranked"][:max_rows]
        ]
        story.append(Paragraph(escape(f"{tr['ranking']} ({weights}; 0–100, relative)"), st["h"]))
        story.append(Paragraph(escape("   ".join(items)), st["p"]))

    story.append(Paragraph(escape(tr["rec"]), st["h"]))
    story.append(Paragraph(escape(summary), st["p"]))

    story.append(Paragraph(escape(tr["limits"]), st["h"]))
    lims = _limitations(result, tr, lang)
    if len(lims) > max_limits:
        truncated.append(f"limitations {len(lims)} -> {max_limits}")
        extra = len(lims) - max_limits + 1
        lims = lims[: max_limits - 1] + [f"(+{extra} more in result.json)"]
    story += [Paragraph(escape(x), st["li"], bulletText="•") for x in lims]

    # Sources: clickable public pages where every number can be checked
    link = '<link href="{}" color="#2a78d6">{}</link>'
    lines = []
    for r in result["results"][:max_rows]:
        src = r.get("sources")
        if not src:
            continue
        parts = [
            link.format(escape(u, {'"': "&quot;"}), escape("Wikipedia: " + unquote(u.rsplit("/wiki/", 1)[-1]).replace("_", " ")))
            for u in src.get("wikipedia", [])
        ]
        parts += [link.format(escape(u), escape(u.rsplit("/", 1)[-1])) for u in src.get("wikidata", [])]
        parts.append(link.format(escape(src["pageviews"], {'"': "&quot;"}), "pageviews"))
        parts.append(link.format(escape(src["edition_total"], {'"': "&quot;"}), "edition total"))
        lines.append(escape(f"{r['topic']} [{r['lang']}]: ") + " · ".join(parts))
    if lines:
        story.append(Paragraph(escape(tr["sources"]), st["h"]))
        story += [Paragraph(x, st["li"], bulletText="•") for x in lines]

    p = result["period"]
    story += [
        Spacer(1, 5),
        Paragraph(
            escape(
                tr["period"].format(start=p["start"], end=p["end"], months=p["months"], today=today().isoformat())
                + f" Source: Wikimedia Pageviews API, agent=user. wiki-analyst {__version__}."
            ),
            st["sub"],
        ),
    ]
    return story, truncated


def _render(story, pagesize=A4) -> tuple[bytes, int]:
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=pagesize, leftMargin=14 * mm, rightMargin=14 * mm,
        topMargin=12 * mm, bottomMargin=12 * mm, title="wiki-analyst report",
    )
    doc.build(story)
    return buf.getvalue(), doc.page


def count_pdf_pages(pdf: bytes) -> int:
    return len(re.findall(rb"/Type\s*/Page(?!s)", pdf))


def build_report(
    run_dir: str | Path,
    summary: str,
    lang: str = "en",
    out: str = "report.pdf",
    chart: str = "indexed",
) -> dict:
    run_dir = Path(run_dir)
    result = load_run(run_dir)
    summary = (summary or "").strip()
    if not summary:
        raise WikiInterestError(
            "--summary is empty.",
            hint="Write 2-4 sentences: the answer, the recommendation, the main caveat. Use only numbers from the run JSON.",
        )
    bad = check_summary_numbers(result, summary)
    if bad:
        raise SummaryGuardError(
            f"--summary contains numbers not present in the run results: {', '.join(bad)}",
            hint="Only quote numbers from the run JSON (e.g. trend_pct_per_year, yoy_pct, trend_ci95) "
            "or remove them, then run report again.",
            offending=bad,
        )
    notes = []
    if lang not in T:
        notes.append(f"no '{lang}' translation of report headings; used English")
        lang = "en"
    tr = T[lang]
    warnings = []
    if len(summary) > 900:
        summary = summary[:880].rsplit(" ", 1)[0] + " …"
        warnings.append("summary truncated to fit one page (keep it to 2-4 sentences)")

    from .charts import make_chart

    chart_path = Path(make_chart(run_dir, chart))  # always fresh; cheap

    fonts = register_fonts()
    pdf, pages, truncated = b"", 0, []
    for layout in LAYOUTS:
        story, truncated = _story(result, summary, tr, chart_path, layout, fonts, lang)
        pdf, pages = _render(story)
        if pages == 1:
            break
    if pages != 1:  # last resort: scale everything into one frame
        story, truncated = _story(result, summary, tr, chart_path, LAYOUTS[-1], fonts, lang)
        frame_w, frame_h = A4[0] - 28 * mm, A4[1] - 24 * mm - 1
        pdf, pages = _render([KeepInFrame(frame_w, frame_h, story, mode="shrink")])
        truncated.append("content shrunk to fit one page")
    if count_pdf_pages(pdf) != 1:
        raise WikiInterestError("Report did not fit on one page.", hint="Shorten --summary and retry.")

    out_path = Path(out)
    if out_path.parent == Path("."):
        out_path = run_dir / out_path  # bare filename -> inside the run dir
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(pdf)
    res = {
        "ok": True,
        "command": "report",
        "report": out_path.as_posix(),
        "pages": 1,
        "lang": lang,
        "chart": Path(chart_path).as_posix(),
    }
    if truncated:
        res["truncated"] = truncated
    if warnings or notes:
        res["warnings"] = warnings + notes
    return res
