"""Portable visual reports without a web service or JavaScript dependency."""

import html
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


def montage(path, reference, expected, actual, window=None):
    # Subtract in float even when the acceptance comparison uses integer data.
    reference, expected, actual = [np.asarray(array, dtype=float)
                                   for array in (reference, expected, actual)]
    ndim = expected.ndim
    lo, hi = window if window is not None else (
        float(min(reference.min(), expected.min(), actual.min())),
        float(max(reference.max(), expected.max(), actual.max())))
    scale = max(hi - lo, 1e-12)
    error_scale = max(float(np.max(np.abs(actual - expected))), 1e-12)
    width, height = 190, 190
    canvas = Image.new("RGB", (5 * width, (ndim if ndim == 3 else 1) * (height + 35)), "white")
    draw = ImageDraw.Draw(canvas)
    for row, axis in enumerate(range(3) if ndim == 3 else [None]):
        def plane(array):
            return np.take(array, array.shape[axis] // 2, axis=axis).T if axis is not None else array.T
        ref, exp, got = map(plane, [reference, expected, actual])
        indices = np.indices(exp.shape)
        tiles = ((indices[0] // 8 + indices[1] // 8) % 2).astype(bool)
        check = np.where(tiles, exp, got)
        for column, (label, array) in enumerate([
            ("reference" + (f" (axis {axis})" if axis is not None else " (x/y)"), ref), (f"package [{lo:.3g}, {hi:.3g}]", exp), ("brainhops", got),
            ("checkerboard", check), (f"abs diff (max {error_scale:.3g})", abs(got - exp)),
        ]):
            pixels = np.clip((array / error_scale if column == 4 else (array - lo) / scale) * 255, 0, 255).astype(np.uint8)
            tile = Image.fromarray(pixels).convert("RGB")
            factor = min(width / tile.width, height / tile.height)
            tile = tile.resize((round(tile.width * factor), round(tile.height * factor)), Image.Resampling.NEAREST)
            x, y = column * width, row * (height + 35)
            draw.text((x + 4, y + 4), label, fill="black")
            canvas.paste(tile, (x + (width - tile.width) // 2, y + 25))
    canvas.save(path)


def write_report(output, result):
    esc = lambda value: html.escape(str(value))
    coverage = result.get("transform_coverage", {})
    coverage_html = ""
    if coverage:
        rows = ''.join('<tr><td>' + '</td><td>'.join(esc(row.get(key, '')) for key in
                       ('family', 'representation', 'origin')) +
                       f'</td><td>{len(row.get("cases", []))}</td></tr>'
                       for row in coverage.get('tested', []))
        gaps = ''.join(f'<li>{esc(row.get("family"))}: {esc(row.get("reason"))}</li>'
                       for row in coverage.get('unavailable', []))
        coverage_html = ('<h2>Transform coverage</h2><p><a href="coverage.json">Native capabilities and tested representations</a>. '
                         'Tested means a native reference was generated; inspect each comparison status below.</p>'
                         '<table><tr><th>Family</th><th>Representation</th><th>Origin</th><th>Cases</th></tr>' +
                         rows + '</table><h3>Unavailable capabilities</h3><ul>' + gaps + '</ul>')
    sections = []
    for case in result["cases"]:
        metrics = case.get("metrics", {})
        sections.append(
            f'<section><h2>{esc(case["id"])}: {esc(case["status"])}</h2>'
            f'<pre>{esc(case.get("error", metrics))}</pre>'
            + (f'<p>Comparison dtype: {esc(case["comparison_dtype"])}</p>'
               f'<h3>Raw float-reference differences (diagnostic)</h3><pre>{esc(case["raw_reference_metrics"])}</pre>'
               if "comparison_dtype" in case else "")
            + (f'<h3>Axis interpretation</h3><pre>{esc(json.dumps(case["axis_interpretation"], indent=2))}</pre>'
               if "axis_interpretation" in case else "")
            + (f'<h3>Warnings</h3><pre>{esc(chr(10).join(case["warnings"]))}</pre>'
               if case.get("warnings") else "")
            + (f'<img loading="lazy" src="{esc(case["preview"])}" alt="Comparison for {esc(case["id"])}">' if "preview" in case else "")
            + "</section>"
        )
    Path(output, "index.html").write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8"><title>brainhops evaluation</title>'
        '<style>body{font:16px system-ui;margin:2rem;max-width:1200px}img{max-width:100%}'
        'pre{white-space:pre-wrap;overflow-wrap:anywhere}section{border-top:1px solid #ccc}</style>'
        '<h1>brainhops evaluation</h1>'
        f'<p>Requested ref: {esc(result["brainhops_ref"])}; resolved commit: {esc(result["brainhops_sha"])}</p>'
        f'<p>Version: {esc(result["brainhops_version"])}; package: {esc(result["backend"])}; interface: {esc(result["interface"])}. '
        'All anatomy and checkerboard panels share the displayed intensity window; only absolute differences use a separate scale. '
        'Slices use reference voxel axes; they are not anatomical orientation labels. '
        'Registration quality is recorded separately in <a href="registration.json">registration.json</a>. '
        'Boundary-only discrepancies have warning status and do not fail the run. Interior discrepancies still fail.</p>'
        '<p>Package values and image panels are converted to the decoded brainhops output dtype. '
        'Integer comparisons require exact interior equality after rounding and saturation. '
        'Differences against the original floating reference remain diagnostic.</p>'
        '<p><a href="results.json">Machine-readable results and provenance</a></p>'
        + coverage_html + "".join(sections) + "</html>"
    )

