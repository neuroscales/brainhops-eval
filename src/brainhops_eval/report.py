"""Portable, human-readable evaluation reports with offline filtering and case pages."""

from __future__ import annotations

import html
import json
from collections import Counter
from importlib.resources import files
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from .files import relative_file
from .report_sections import (
    issue_table,
    quantitative_table,
    registration_table,
    software_navigation,
    statistics_tables,
    status_badge,
    visual_gallery,
)
from .statistics import STATUS_LABELS, case_summary, software_name
from .types import Array, PathLike, Record

_STATUS_ORDER = {"error": 0, "fail": 1, "warning": 2, "pass": 3}
_STATUS_MEANING = {
    "pass": "Interior and boundary thresholds satisfied",
    "warning": "Interior passes; boundary-only differences",
    "fail": "Interior values or axis interpretation disagree",
    "error": "Reader, application, or validation raised an exception",
}


def montage(
    path: PathLike,
    reference: Array,
    expected: Array,
    actual: Array,
    window: tuple[float, float] | list[float] | None = None,
) -> None:
    """Save orthogonal comparisons using one shared anatomy window.

    Absolute differences have their own labelled scale. Images use reference
    voxel axes; these axis numbers are not anatomical orientation labels.
    """
    # Subtract in float even when the acceptance comparison uses integer data.
    reference, expected, actual = [
        np.asarray(array, dtype=float) for array in (reference, expected, actual)
    ]
    ndim = expected.ndim
    lo, hi = (
        window
        if window is not None
        else (
            float(min(reference.min(), expected.min(), actual.min())),
            float(max(reference.max(), expected.max(), actual.max())),
        )
    )
    scale = max(hi - lo, 1e-12)
    error_scale = max(float(np.max(np.abs(actual - expected))), 1e-12)
    width, height = 190, 190
    canvas = Image.new("RGB", (5 * width, (ndim if ndim == 3 else 1) * (height + 35)), "white")
    draw = ImageDraw.Draw(canvas)
    for row, axis in enumerate(range(3) if ndim == 3 else [None]):

        def plane(array: Array, axis: int | None = axis) -> Array:
            return (
                np.take(array, array.shape[axis] // 2, axis=axis).T if axis is not None else array.T
            )

        ref, exp, got = map(plane, [reference, expected, actual])
        indices = np.indices(exp.shape)
        tiles = ((indices[0] // 8 + indices[1] // 8) % 2).astype(bool)
        check = np.where(tiles, exp, got)
        for column, (label, array) in enumerate(
            [
                ("reference" + (f" (axis {axis})" if axis is not None else " (x/y)"), ref),
                (f"package [{lo:.3g}, {hi:.3g}]", exp),
                ("brainhops", got),
                ("checkerboard", check),
                (f"abs diff (max {error_scale:.3g})", abs(got - exp)),
            ]
        ):
            pixels = np.clip(
                (array / error_scale if column == 4 else (array - lo) / scale) * 255, 0, 255
            ).astype(np.uint8)
            tile = Image.fromarray(pixels).convert("RGB")
            factor = min(width / tile.width, height / tile.height)
            tile = tile.resize(
                (round(tile.width * factor), round(tile.height * factor)), Image.Resampling.NEAREST
            )
            x, y = column * width, row * (height + 35)
            draw.text((x + 4, y + 4), label, fill="black")
            canvas.paste(tile, (x + (width - tile.width) // 2, y + 25))
    canvas.save(path)


_BOUNDARY_LABELS = {
    "grid-constant": "Zero-extended grid interpolation",
    "nearest-clip-half-closed": "Nearest-edge interpolation; closed half-voxel cutoff",
    "mirror-clip-half-closed": "Mirror interpolation; closed half-voxel cutoff",
    "nearest-clip-centres-closed": "Nearest-edge interpolation; closed voxel-centre cutoff",
    "constant": "Zero outside voxel centres",
    "nearest": "Extend edge values indefinitely",
    "reflect": "Reflect at the outer edge",
    "mirror": "Mirror about edge voxel centres",
    "half-voxel-clamp": "Clamp within the half-voxel extent; zero outside",
    "strict-half-voxel-clamp": "Clamp strictly inside the half-voxel extent; zero at/outside endpoints",
    "half-voxel-mirror": "Mirror interpolation inside the half-voxel extent; zero outside",
    "center-clipped-background": "Clip to voxel-centre FOV; use measured background outside",
}


def _escape(value: object) -> str:
    """Escape user/package text for HTML attributes and visible content."""
    return html.escape(str(value), quote=True)


def _badge(status: str) -> str:
    """Render a text status badge; colour is never its only meaning."""
    return status_badge(status)


def page_document(title: str, content: str, prefix: str = "") -> str:
    """Wrap a report page using local assets so downloaded reports work offline."""
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{_escape(title)}</title><link rel="stylesheet" href="{prefix}report.css">'
        f'<script defer src="{prefix}report.js"></script></head><body><main>{content}'
        "<footer>brainhops evaluation · Native outputs are references, not proof of registration accuracy. "
        "Warnings do not fail interior acceptance; failures and errors do.</footer></main></body></html>"
    )


def _stats(cases: list[Record]) -> str:
    """Display case counts and the precise meaning of each status."""
    counts = Counter(case["status"] for case in cases)
    cards = "".join(
        f'<div class="stat {status}"><strong>{counts[status]:,}</strong>'
        f"{STATUS_LABELS[status]}<br><small>{meaning}</small></div>"
        for status, meaning in _STATUS_MEANING.items()
    )
    return f'<div class="stats">{cards}</div>'


def _filters(cases: list[Record]) -> str:
    """Provide accessible status, family and text filters without a web service."""
    families = sorted({str(case.get("transform_family") or "affine") for case in cases})
    options = "".join(
        f'<option value="{_escape(value)}">{_escape(value)}</option>' for value in families
    )
    return (
        '<div class="filters"><label>Search cases<input id="search" type="search" placeholder="Transform, file, or failure reason"></label>'
        '<label>Status<select id="status"><option value="">All statuses</option>'
        + "".join(f"<option>{status}</option>" for status in _STATUS_ORDER)
        + '</select></label><label>Transform family<select id="family"><option value="">All families</option>'
        + options
        + '</select></label></div><p class="muted" id="visible-count"></p>'
    )


def _coverage(result: Record) -> str:
    """Separate generated native references from unsupported native capabilities."""
    coverage = result.get("transform_coverage", {})
    if not coverage:
        return ""
    rows = "".join(
        "<tr>"
        + "".join(
            f"<td>{_escape(row.get(key, ''))}</td>"
            for key in ("family", "representation", "origin")
        )
        + f"<td>{len(row.get('cases', []))}</td></tr>"
        for row in coverage.get("tested", [])
    )
    gaps = "".join(
        f"<li><strong>{_escape(row.get('family'))}</strong>: {_escape(row.get('reason'))}</li>"
        for row in coverage.get("unavailable", [])
    )
    return (
        '<details class="card"><summary>Transform coverage and native capability gaps</summary>'
        "<p>Tested means a native reference was generated; inspect each comparison status. "
        '<a href="coverage.json">Download coverage.json</a>.</p>'
        f"<p>{len(coverage.get('tested', []))} representations generated native cases.</p>"
        "<table><tr><th>Family</th><th>Representation</th><th>Origin</th><th>Cases</th></tr>"
        + rows
        + f"</table><h3>Unavailable capabilities</h3><ul>{gaps or '<li>None recorded.</li>'}</ul></details>"
    )


def _metrics(case: Record) -> str:
    """Present observed interior values beside the actual pass/fail thresholds."""
    metrics = case.get("metrics")
    if not metrics:
        return "<p>No numerical comparison was reached.</p>"
    rows = []
    for label, key, limit in [
        ("Maximum absolute error", "interior_max_abs", "atol"),
        ("Normalised RMSE", "interior_nrmse", "nrmse_limit"),
        ("Integer mismatch count", "interior_mismatch_count", None),
    ]:
        if key not in metrics:
            continue
        value = metrics[key]
        threshold = metrics[limit] if limit else 0
        status = "pass" if value <= threshold else "fail"
        rows.append(
            f'<tr><td>{label}</td><td class="numeric">{value:.6g}</td>'
            f'<td class="numeric">≤ {threshold:.6g}</td><td>{_badge(status)}</td></tr>'
        )
    return (
        "<h2>Interior acceptance</h2><p>Both maximum error and normalised RMSE must pass. NRMSE divides RMSE by the reference intensity range (at least one). "
        "Integer output requires zero differing interior voxels.</p>"
        "<table><tr><th>Measure</th><th>Observed</th><th>Required</th><th>Check</th></tr>"
        + "".join(rows)
        + "</table>"
        + f"<p>Interior covers {metrics['interior_fraction']:.1%} of the reference grid. "
        f"Boundary maximum error: {metrics['boundary_max_abs']:.6g} (nonblocking). "
        f"Boundary NRMSE: {metrics.get('boundary_nrmse', 0):.6g}.</p>"
    )


def _metadata(case: Record) -> str:
    """Explain files, reslice settings, dtype and boundary convention for one case."""
    boundary = case.get("boundary_policy", {})
    items = [
        ("Moving image", case.get("moving", case.get("input", {}))),
        ("Reference image", case.get("reference_image", case.get("reference", {}))),
        ("Transform", case.get("transform")),
        ("Reader hint", case.get("transform_hint")),
        ("Application interface", case.get("interface", "not recorded")),
        ("Interpolation degree", case.get("degree", "not recorded")),
        ("Output / comparison dtype", case.get("comparison_dtype", "not produced")),
        ("Native reference dtype", case.get("reference_output_dtype", "not recorded")),
        ("brainhops boundary", boundary.get("brainhops_bound", "constant")),
        ("brainhops clip margin", boundary.get("brainhops_clip")),
        ("Boundary approximation", boundary.get("note", "not recorded")),
        ("Capability fallback", boundary.get("capability_fallback", "")),
        ("Native boundary convention", boundary.get("native_rule", "not recorded")),
    ]
    return (
        '<dl class="meta">'
        + "".join(
            f"<dt>{label}</dt><dd><code>{_escape(value)}</code></dd>" for label, value in items
        )
        + "</dl>"
    )


def _details(case: Record) -> str:
    """Keep tracebacks and machine diagnostics available without overwhelming the page."""
    sections = []
    if case.get("error"):
        sections.append(
            "<h2>Application error</h2><p>Stage: "
            + _escape(case.get("stage", "not recorded"))
            + "</p>"
            f"<pre>{_escape(case.get('error_summary', case['error'].strip().splitlines()[-1]))}</pre>"
            f"<details><summary>Full traceback</summary><pre>{_escape(case['error'])}</pre></details>"
        )
    for key, title in [
        ("axis_interpretation", "Axis interpretation"),
        ("warnings", "Warnings"),
        ("raw_reference_metrics", "Differences before reference dtype conversion"),
    ]:
        if case.get(key):
            sections.append(
                f"<details><summary>{title}</summary><pre>{_escape(json.dumps(case[key], indent=2))}</pre></details>"
            )
    return "".join(sections)


def _write_case(output: Path, case: Record, result: Record) -> None:
    """Write an individual case with explanation, thresholds, montage and drill-down."""
    directory = relative_file(output, case["id"])
    directory.mkdir(exist_ok=True)
    header = (
        '<p><a href="../index.html">← All cases</a></p><header><div class="eyebrow">'
        + _escape(result["backend"])
        + " · "
        + _escape(result["brainhops_sha"])
        + "</div>"
        + f"<h1>{_escape(case['id'])}</h1>{_badge(case['status'])}"
        + f"<p>{_escape(case_summary(case))}</p></header>"
    )
    preview = ""
    if "preview" in case:
        preview = (
            '<h2>Visual comparison</h2><figure><img loading="lazy" src="comparison.png" '
            'alt="Reference, native package, brainhops, checkerboard and absolute differences">'
            "<figcaption>All anatomy/checkerboard panels share one intensity window. "
            "Absolute differences use their labelled scale. Slices follow reference voxel axes.</figcaption></figure>"
        )
    content = (
        _site_menu(result, "../../")
        + header
        + '<section class="panel">'
        + _metadata(case)
        + _metrics(case)
        + preview
        + _details(case)
        + "</section>"
    )
    (directory / "index.html").write_text(page_document(case["id"], content, "../"))


def _site_menu(result: Record, prefix: str) -> str:
    """Add software navigation only when a report belongs to a published portal."""
    items = result.get("_site_navigation", [])
    return software_navigation(items, prefix=prefix, current=result["backend"]) if items else ""


def write_report(output: PathLike, result: Record) -> None:
    """Write an offline report index, per-case pages, and local CSS/JS assets."""
    output = Path(output)
    copy_assets(output)
    for case in result["cases"]:
        _write_case(output, case, result)
    header = (
        '<header><div class="eyebrow">Registration & resampling interoperability</div>'
        f"<h1>{_escape(software_name(result['backend']))} results</h1>"
        f"<p><strong>{_escape(result['backend'])}</strong> · {_escape(result['interface'])} interface · "
        f"brainhops {_escape(result['brainhops_version'])}</p>"
        f"<p>Requested ref: <code>{_escape(result['brainhops_ref'])}</code><br>"
        f"Resolved commit: <code>{_escape(result['brainhops_sha'])}</code></p>"
        '<p class="downloads"><a href="results.json">Download full results (JSON)</a> · '
        '<a href="registration.json">Download native registration provenance</a></p></header>'
    )
    policy = (
        '<section class="panel"><h2>How to read this report</h2>'
        "<p>Native package output is compared in the decoded brainhops output dtype. "
        "Integer values must match exactly after rounding and saturation of the reference. "
        "Floating-point output must pass both stated interior thresholds. "
        "Boundary-only differences warn; input axes, interior discrepancies and application errors fail.</p>"
        "<p>brainhops images are used directly from its readers. No replacement images, input casts, "
        "axis fixes or geometry adapters are applied.</p></section>"
    )
    boundary = _boundary_probe(result)
    content = (
        _site_menu(result, "../")
        + header
        + '<nav class="section-nav" aria-label="Results sections"><a href="#issues">Failure types</a><a href="#statistics">Statistics</a><a href="#quantitative">Numerical results</a><a href="#qualitative">Images</a></nav>'
        + _stats(result["cases"])
        + issue_table(result["cases"])
        + statistics_tables(result["cases"])
        + policy
        + registration_table(result)
        + _coverage(result)
        + boundary
        + '<section id="quantitative"><h2>Numerical results by case</h2>'
        + _filters(result["cases"])
        + quantitative_table(result["cases"])
        + "</section>"
        + visual_gallery(result["cases"])
    )
    (output / "index.html").write_text(page_document("brainhops evaluation", content))


def copy_assets(output: PathLike) -> None:
    """Copy local report assets into a generated report or portal directory."""
    output = Path(output)
    for name in ("report.css", "report.js"):
        asset = files("brainhops_eval").joinpath("assets", name)
        (output / name).write_text(asset.read_text())


def _boundary_curve(probe: Record, sample: Record) -> str:
    """Plot native ramp samples against public constant-padding predictions."""
    values = sample.get("model_values", {}).get("grid-constant")
    if not values:
        return ""
    x = np.asarray(probe["sample_x_voxels"])
    native = np.asarray(sample["native_values"])
    upper = max(float(max(native.max(), max(values))), 1)

    def points(series: Array) -> str:
        """Project sampled coordinates into the static SVG viewport."""
        px = 45 + (x - x.min()) / max(float(np.ptp(x)), 1e-12) * 800
        py = 185 - np.asarray(series) / upper * 150
        return " ".join(f"{a:.2f},{b:.2f}" for a, b in zip(px, py, strict=True))

    return (
        '<svg viewBox="0 0 880 230" role="img" aria-label="Native edge samples versus grid-zero padding">'
        '<path d="M45 25V185H850" stroke="#8795a6" fill="none"/>'
        f'<polyline points="{points(native)}" fill="none" stroke="#182738" stroke-width="2"/>'
        f'<polyline points="{points(np.asarray(values))}" fill="none" stroke="#1769bf" stroke-width="2" stroke-dasharray="6 4"/>'
        f'<text x="10" y="40" font-size="12">{upper:.3g}</text><text x="20" y="190" font-size="12">0</text>'
        f'<text x="42" y="205" font-size="12">{x.min():g}</text><text x="820" y="205" font-size="12">{x.max():g}</text>'
        '<text x="300" y="225" font-size="13">Source x coordinate in voxels</text></svg>'
        "<figcaption>Black: native image samples. Dashed blue: grid-zero interpolation "
        "(brainhops constant). This is an independent float-ramp probe.</figcaption>"
    )


def _boundary_probe(result: Record) -> str:
    """Explain measured image-edge behavior separately from transformation support."""
    probe = result.get("boundary_probes")
    if not probe:
        return ""
    rows, plots = [], []
    for sample in probe["interpolation"]:
        error = sample["model_errors"]["grid-constant"]["max_abs"]
        matches = (
            "; ".join(_BOUNDARY_LABELS.get(name, name) for name in sample["matching_models"])
            or "No tested rule matched"
        )
        rows.append(
            f"<tr><td>{sample['degree']}</td><td>{_escape(matches)}</td>"
            f'<td class="numeric">{error:.6g}</td><td>{sample.get("measured_far_background", "not recorded")}</td></tr>'
        )
        plots.append(
            f"<h3>Interpolation degree {sample['degree']}</h3>" + _boundary_curve(probe, sample)
        )
    return (
        '<details class="card"><summary>Measured image boundary conventions</summary>'
        "<p>These probes distinguish padding, half-voxel clipping/clamping, and estimated background. "
        "They do not establish nonlinear transform-field support. A rule that lacks a public brainhops "
        "equivalent remains a documented boundary warning; loaded images are never patched.</p>"
        "<table><tr><th>Degree</th><th>Matching native rule</th><th>Max difference from constant</th>"
        "<th>Far-background sample</th></tr>"
        + "".join(rows)
        + "</table>"
        + "".join(plots)
        + '<p><a href="boundary-probes.json">Full samples, model residuals and provenance</a></p></details>'
    )


def markdown_summary(result: Record, limit: int = 30) -> str:
    """Summarise status counts and actionable failures for the Actions job summary."""
    counts = Counter(case["status"] for case in result["cases"])
    lines = [
        f"## {result['backend']} evaluation",
        f"brainhops commit: `{result['brainhops_sha']}`",
        "",
        " · ".join(f"{counts[status]} {status}" for status in ("pass", "warning", "fail", "error")),
        "",
        "Boundary-only warnings do not fail acceptance. Interior/axis failures and errors do.",
        "",
        "| Case | Status | Why |",
        "| --- | --- | --- |",
    ]
    cases = sorted(result["cases"], key=lambda c: (_STATUS_ORDER.get(c["status"], 4), c["id"]))
    for case in cases[:limit]:
        reason = case_summary(case).replace("|", "\\|").replace("\n", " ")
        identifier = case["id"].replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {identifier} | {case['status']} | {reason} |")
    if len(cases) > limit:
        lines.extend(["", f"{len(cases) - limit} more cases are in the full HTML report."])
    lines.extend(
        [
            "",
            "Download the report artifact and open index.html for filtered results, thresholds and montages.",
            "Main-branch runs are also published to GitHub Pages after completion.",
        ]
    )
    return "\n".join(lines) + "\n"
