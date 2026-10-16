"""Assemble a static GitHub Pages portal from one evaluation run's artifacts.

Only report HTML, montages, styles and quantitative JSON are published. Full
resliced images and logs remain in the downloadable Actions report artifacts.
Pages represents the latest deployment; Actions retains previous run artifacts.
"""

from __future__ import annotations

import html
import re
import shutil
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

from .files import read_json, relative_file, write_json
from .report import copy_assets, page_document, write_report
from .report_sections import software_navigation, status_badge
from .statistics import ISSUE_LABELS, STATUSES, software_name, software_statistics
from .types import PathLike, Record

_PUBLISHED_SUFFIXES = frozenset({".html", ".png", ".css", ".js", ".json"})
_BACKEND_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def _copy_report(source: Path, target: Path, result: Record, navigation: list[Record]) -> None:
    """Publish display/JSON assets and refresh legacy reports to the current UI."""
    for path in source.rglob("*"):
        if path.is_file() and path.suffix.lower() in _PUBLISHED_SUFFIXES:
            destination = target / path.relative_to(source)
            destination.parent.mkdir(parents=True, exist_ok=True)
            safe_source = relative_file(source, path.relative_to(source))
            shutil.copyfile(safe_source, destination)
    write_report(target, {**result, "_site_navigation": navigation})


def _failure_types(summary: Record) -> str:
    """Name failing transform families and numerical/reader checks in the overview."""
    esc = html.escape
    families = ", ".join(f"{name} ({count})" for name, count in summary["failed_families"].items())
    reasons = "; ".join(
        f"{ISSUE_LABELS.get(code, code)} ({count})"
        for code, count in summary["failure_reasons"].items()
    )
    boundary = summary["boundary_cases"]
    return (
        "<strong>Families:</strong> "
        + esc(families or "No blocking failures")
        + "<br><strong>Checks:</strong> "
        + esc(reasons or "All blocking checks pass")
        + (
            f"<br><small>Boundary discrepancies in {boundary} tests (nonblocking).</small>"
            if boundary
            else ""
        )
    )


def _software_table(manifest: Record) -> str:
    """Give one global row per software, including failed test categories and counts."""
    rows = []
    for summary in manifest["software"]:
        name = html.escape(software_name(summary["backend"]))
        path = quote(summary["paths"][0], safe="/")
        counts = "".join(
            f'<td class="numeric {status}" aria-label="{summary["counts"][status]} {status}">{summary["counts"][status]}</td>'
            for status in STATUSES
        )
        rows.append(
            f'<tr><th scope="row"><a href="{path}/index.html">{name}</a><br><small>{html.escape(", ".join(summary["interfaces"]))}</small></th>'
            + f'<td>{status_badge(summary["status"])}</td><td class="numeric">{summary["total"]}</td>'
            + counts
            + f'<td class="failure-types">{_failure_types(summary)}</td><td><a class="button-link" href="{path}/index.html">Full results & images →</a></td></tr>'
        )
    for name in manifest["missing_reports"]:
        rows.append(
            f'<tr><th scope="row">{html.escape(name)}</th><td>{status_badge("incomplete")}</td><td colspan="7">No report produced. Inspect generation/evaluation logs in Actions.</td></tr>'
        )
    return (
        '<section class="panel" id="software-summary"><h2>Results by software</h2>'
        "<p><strong>Success:</strong> every check passes. <strong>Warning:</strong> only boundary differences. "
        "<strong>Fail:</strong> interior/axis checks fail or execution errors occur. Open a software page for grouped statistics, all numerical comparisons and inline montages.</p>"
        '<div class="table-scroll"><table class="software-table"><thead><tr><th>Software</th><th>Overall</th><th>Tests</th><th>Success</th><th>Warn</th><th>Fail</th><th>Error</th><th>Which tests fail?</th><th>Explore</th></tr></thead><tbody>'
        + "".join(rows)
        + '</tbody></table></div><p class="muted">Failure reasons can overlap within a test. Boundary differences can accompany a blocking failure; they never decide interior acceptance.</p></section>'
    )


def build_site(reports: PathLike, output: PathLike, run_url: str = "") -> Record:
    """Build a static run overview plus per-backend reports from artifact folders.

    Reject mixed brainhops commits and duplicate backend/interface pairs. A run
    with no results gets an explicit incomplete page, so failed generation is
    never represented as a successful empty evaluation.
    """
    reports, output = Path(reports), Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError("Use an empty site output directory")
    results = [(path.parent, read_json(path)) for path in sorted(reports.rglob("results.json"))]
    commits = {result["brainhops_sha"] for _, result in results}
    if len(commits) > 1:
        raise ValueError("Cannot publish mixed brainhops commits as one evaluation run")
    contexts = list(reports.rglob("evaluation-context.json"))
    if len(contexts) > 1:
        raise ValueError("Expected one evaluation run context")
    context = read_json(contexts[0]) if contexts else {}
    if commits and context and context["brainhops_sha"] not in commits:
        raise ValueError("Run context and report brainhops commits disagree")
    output.mkdir(parents=True, exist_ok=True)
    names, summaries, navigation = set(), [], []
    for _, result in results:
        name = result["backend"] + "-" + result["interface"]
        if not _BACKEND_NAME.fullmatch(name) or name in names:
            raise ValueError(f"Invalid or duplicate report backend/interface: {name}")
        names.add(name)
        result["_report_path"] = name
        navigation.append(dict(backend=result["backend"], path=name))
    for source, result in results:
        name = result["_report_path"]
        _copy_report(source, output / name, result, navigation)
        summaries.append(
            dict(
                backend=result["backend"],
                interface=result["interface"],
                path=name,
                counts=dict(Counter(case["status"] for case in result["cases"])),
                passed=bool(result.get("passed")),
            )
        )
    sha = next(iter(commits), context.get("brainhops_sha", "No version evaluated"))
    expected = {backend + "-" + context["interface"] for backend in context.get("packages", [])}
    missing = sorted(expected - names)
    complete = bool(results) and not missing if context else (None if results else False)
    manifest = dict(
        schema_version=1,
        brainhops_sha=sha,
        run_url=run_url,
        generated_at=datetime.now(UTC).isoformat(),
        reports=summaries,
        software=software_statistics([result for _, result in results]),
        navigation=navigation,
        complete=complete,
        missing_reports=missing,
        coverage_known=bool(context),
        passed=complete is True and all(r["passed"] for r in summaries),
    )
    write_json(output / "site.json", manifest)
    copy_assets(output)
    _write_overview(output, manifest)
    return manifest


def _write_overview(output: Path, manifest: Record) -> None:
    """Explain the deployed version, run provenance and historical artifact retention."""
    esc = html.escape
    run_link = ""
    if manifest["run_url"].startswith("https://github.com/"):
        run_link = f'<p><a href="{esc(manifest["run_url"], quote=True)}">Actions run, logs and full downloadable artifacts</a></p>'
    header = (
        '<header><div class="eyebrow">Native registration interoperability</div>'
        "<h1>brainhops evaluation results</h1><p>brainhops commit: "
        f"<code>{esc(manifest['brainhops_sha'])}</code></p>{run_link}"
        "<p>This site shows the latest published run. Earlier evaluations remain in their "
        "Actions artifacts for 90 days. Reports are published even when comparisons fail.</p></header>"
    )
    empty = '<p class="notice error">No backend produced a report. Evaluation is incomplete; inspect the Actions run.</p>'
    notice = ""
    if manifest["missing_reports"]:
        notice = (
            '<p class="notice error">Missing reports: '
            + esc(", ".join(manifest["missing_reports"]))
            + ". This run is incomplete.</p>"
        )
    elif not manifest["coverage_known"] and manifest["reports"]:
        notice = '<p class="notice warning">Legacy run has no package manifest; completeness cannot be verified.</p>'
    content = (
        software_navigation(manifest["navigation"])
        + header
        + notice
        + (_software_table(manifest) if manifest["reports"] else empty)
    )
    (output / "index.html").write_text(page_document("brainhops evaluation results", content))
    (output / ".nojekyll").touch()
