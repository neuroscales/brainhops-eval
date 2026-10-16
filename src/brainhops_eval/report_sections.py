"""Human-readable tables, navigation and image galleries for static reports."""

from __future__ import annotations

import hashlib
import html
from collections.abc import Callable
from urllib.parse import quote

from .statistics import (
    ISSUE_LABELS,
    STATUS_LABELS,
    STATUSES,
    case_order,
    case_summary,
    family,
    format_number,
    group_statistics,
    image_kind,
    issue_codes,
    issue_counts,
    software_name,
)
from .types import Record


def _escape(value: object) -> str:
    """Escape recorded software/image text before inserting it into HTML."""
    return html.escape(str(value), quote=True)


def status_badge(status: str) -> str:
    """Render an explicit text status, preserving the machine status as its class."""
    return (
        f'<span class="badge {_escape(status)}">{_escape(STATUS_LABELS.get(status, status))}</span>'
    )


def software_navigation(items: list[Record], *, prefix: str = "", current: str = "") -> str:
    """Provide a persistent software menu and a global overview on every site page."""
    links = [
        f'<a href="{prefix}index.html"'
        + (' aria-current="page"' if not current else "")
        + ">All software</a>"
    ]
    seen = set()
    for item in items:
        name = item["backend"]
        if name in seen:
            continue
        seen.add(name)
        active = ' aria-current="page"' if name == current else ""
        href = prefix + quote(item["path"], safe="/") + "/index.html"
        links.append(f'<a href="{href}"{active}>{_escape(software_name(name))}</a>')
    return '<nav class="software-nav" aria-label="Software results">' + "".join(links) + "</nav>"


def _count_cells(counts: Record) -> str:
    """Show all outcome counts, including zeros, with accessible labels."""
    return "".join(
        f'<td class="numeric {status}" aria-label="{counts[status]} {status}">{counts[status]:,}</td>'
        for status in STATUSES
    )


def _group_table(cases: list[Record], key: Callable[[Record], str], title: str) -> str:
    """Show counts and numerical extrema for one recorded test dimension."""
    rows = []
    for row in group_statistics(cases, key):
        reasons = (
            "; ".join(
                f"{ISSUE_LABELS.get(code, code)} ({count})"
                for code, count in row["reasons"].items()
            )
            or "No blocking failures"
        )
        rows.append(
            f'<tr><th scope="row">{_escape(row["label"])}</th><td class="numeric">{row["total"]}</td>'
            + _count_cells(row["counts"])
            + f'<td class="numeric">{format_number(row["interior_max_abs"])}</td><td class="numeric">{format_number(row["interior_nrmse"])}</td><td>{_escape(reasons)}</td></tr>'
        )
    return (
        f'<h3>{title}</h3><div class="table-scroll"><table><thead><tr><th>{title}</th><th>Tests</th><th>Success</th><th>Warn</th><th>Fail</th><th>Error</th><th>Worst interior max</th><th>Worst NRMSE</th><th>Failing checks</th></tr></thead><tbody>'
        + "".join(rows)
        + "</tbody></table></div>"
    )


def statistics_tables(cases: list[Record]) -> str:
    """Expose numerical test statistics directly, grouped by meaningful dimensions."""
    groups = [
        (family, "Transform family"),
        (lambda case: str(case.get("comparison_dtype", "No output")), "Output dtype"),
        (
            lambda case: {0: "Nearest neighbour (0)", 1: "Linear (1)"}.get(
                case.get("degree"), str(case.get("degree", "Not recorded"))
            ),
            "Image interpolation",
        ),
        (image_kind, "Image format"),
    ]
    tables = "".join(_group_table(cases, key, title) for key, title in groups)
    return (
        '<section class="panel" id="statistics"><h2>Test statistics</h2><p>Whole-run counts, grouped by the recorded transform, output dtype, image interpolation and format. A test appears once in each grouping. A dash means the numerical comparison was not reached. Maxima are per-case extrema, not pooled registration-accuracy scores; image intensity ranges and dtype tolerances differ.</p>'
        + tables
        + "</section>"
    )


def issue_table(cases: list[Record]) -> str:
    """Separate blocking reasons from boundary warnings, with affected test families."""
    rows = []
    for code, count in sorted(
        issue_counts(cases).items(),
        key=lambda item: (item[0] == "boundary-difference", -item[1], item[0]),
    ):
        affected = sorted({family(case) for case in cases if code in issue_codes(case)})
        effect = "Warning only" if code == "boundary-difference" else "Blocking failure"
        rows.append(
            f'<tr><th scope="row">{_escape(ISSUE_LABELS.get(code, code))}</th><td class="numeric">{count}</td><td>{effect}</td><td>{_escape(", ".join(affected))}</td></tr>'
        )
    if not rows:
        return '<section class="panel" id="issues"><h2>Failure and warning breakdown</h2><p>All recorded checks succeeded.</p></section>'
    return (
        '<section class="panel" id="issues"><h2>Failure and warning breakdown</h2><p>Counts are affected tests, not voxels. One test can have several reasons, so these rows need not sum to the total test count.</p><div class="table-scroll"><table><thead><tr><th>Type of discrepancy</th><th>Affected tests</th><th>Effect</th><th>Transform families</th></tr></thead><tbody>'
        + "".join(rows)
        + "</tbody></table></div></section>"
    )


def _anchor(case: Record) -> str:
    """Make a safe stable image anchor without changing visible case identifiers."""
    return "visual-" + hashlib.sha256(case["id"].encode()).hexdigest()[:12]


def _case_attributes(case: Record) -> str:
    """Give numerical rows and visual cards identical searchable metadata."""
    text = " ".join(
        str(value)
        for value in [
            case["id"],
            family(case),
            case.get("comparison_dtype", ""),
            case.get("transform_representation", ""),
            case_summary(case),
        ]
    )
    return f'data-case-status="{_escape(case["status"])}" data-family="{_escape(family(case))}" data-case-search="{_escape(text.lower())}"'


def _observed_limit(metrics: Record, key: str, limit: str) -> str:
    """Display an observed value and its actual per-case acceptance limit."""
    return (
        format_number(metrics.get(key))
        + "<br><small>limit "
        + format_number(metrics.get(limit))
        + "</small>"
        if key in metrics
        else "—"
    )


def quantitative_table(cases: list[Record]) -> str:
    """Show all per-case numerical results and thresholds without opening JSON."""
    rows = []
    for case in sorted(cases, key=case_order):
        metrics = case.get("metrics", {})
        link = "./" + quote(case["id"], safe="") + "/index.html"
        mismatch = format_number(metrics.get("interior_mismatch_count"))
        if "interior_voxel_count" in metrics:
            mismatch += f"<br><small>of {metrics['interior_voxel_count']:,} voxels</small>"
        visual = (
            f'<a href="#{_anchor(case)}">View image ↓</a>'
            if case.get("preview")
            else "No image produced"
        )
        rows.append(
            f'<tr {_case_attributes(case)}><td>{status_badge(case["status"])}</td><th scope="row" class="case-name"><a href="{link}">{_escape(case["id"])}</a><br><small>{_escape(family(case))} · {_escape(case.get("comparison_dtype", "no output"))}</small></th><td class="reason">{_escape(case_summary(case))}</td><td class="numeric">{_observed_limit(metrics, "interior_max_abs", "atol")}</td><td class="numeric">{_observed_limit(metrics, "interior_nrmse", "nrmse_limit")}</td><td class="numeric">{mismatch}</td><td class="numeric">{format_number(metrics.get("boundary_max_abs"))}</td><td>{visual}</td></tr>'
        )
    return (
        '<div class="table-scroll"><table class="case-table"><thead><tr><th>Status</th><th>Case / family / dtype</th><th>Why this result?</th><th>Interior max error</th><th>Interior NRMSE</th><th>Integer mismatches</th><th>Boundary max</th><th>Qualitative</th></tr></thead><tbody>'
        + "".join(rows)
        + "</tbody></table></div>"
    )


def visual_gallery(cases: list[Record]) -> str:
    """Place every available montage directly on the software page, failure first."""
    cards = []
    for case in sorted(cases, key=case_order):
        if not case.get("preview"):
            continue
        src = "./" + quote(case["preview"], safe="/")
        detail = "./" + quote(case["id"], safe="") + "/index.html"
        metrics = case.get("metrics", {})
        cards.append(
            f'<article class="case-visual" id="{_anchor(case)}" {_case_attributes(case)}><div class="visual-heading"><h3>{_escape(case["id"])}</h3>{status_badge(case["status"])}</div><p>{_escape(case_summary(case))}</p><p class="visual-numbers">Interior max: <strong>{format_number(metrics.get("interior_max_abs"))}</strong> · NRMSE: <strong>{format_number(metrics.get("interior_nrmse"))}</strong> · Boundary max: <strong>{format_number(metrics.get("boundary_max_abs"))}</strong></p><figure><a href="{src}"><img loading="lazy" src="{src}" alt="{_escape(case["id"])}: reference, native output, brainhops output, checkerboard, and absolute difference" width="950"></a><figcaption>{_escape(family(case))} · {_escape(case.get("comparison_dtype", "unknown dtype"))}. Anatomy panels share one intensity window; absolute differences have a separate labelled scale.</figcaption></figure><a href="{detail}">Full case settings, thresholds and diagnostics →</a></article>'
        )
    return (
        '<section id="qualitative"><h2>Qualitative comparisons</h2><p>Montages are shown directly below, ordered by status. The case filters also apply to these images. Click an image for its full resolution.</p>'
        + ("".join(cards) or '<p class="notice">No montage was produced by this evaluation.</p>')
        + "</section>"
    )


def registration_table(result: Record) -> str:
    """Present native registration settings and measurements as readable table rows."""

    def rows(value: object, path: str = "") -> list[str]:
        """Flatten nested native provenance without requiring a JSON reader."""
        if isinstance(value, dict):
            return [
                row
                for key, item in value.items()
                for row in rows(item, f"{path} / {key}" if path else str(key))
            ]
        if isinstance(value, list):
            text = ", ".join(
                format_number(item) if isinstance(item, (int, float)) else str(item)
                for item in value
            )
        else:
            text = str(value) if value is not None else "Not recorded"
        return [
            f'<tr><th scope="row">{_escape(path.replace("_", " "))}</th><td>{_escape(text)}</td></tr>'
        ]

    data = result.get("registration", {})
    if not data:
        return ""
    return (
        '<details class="card"><summary>Native registration measurements and settings</summary><p>These describe the native registration run; image-resampling agreement is measured in the tables above.</p><table><thead><tr><th>Measurement / setting</th><th>Value</th></tr></thead><tbody>'
        + "".join(rows(data))
        + "</tbody></table></details>"
    )
