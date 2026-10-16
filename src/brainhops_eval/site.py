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
from .report import case_summary, copy_assets, page_document, write_report
from .types import PathLike, Record

_PUBLISHED_SUFFIXES = frozenset({".html", ".png", ".css", ".js", ".json"})
_BACKEND_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def _copy_report(source: Path, target: Path, result: Record) -> None:
    """Publish display/JSON assets and refresh legacy reports to the current UI."""
    for path in source.rglob("*"):
        if path.is_file() and path.suffix.lower() in _PUBLISHED_SUFFIXES:
            destination = target / path.relative_to(source)
            destination.parent.mkdir(parents=True, exist_ok=True)
            safe_source = relative_file(source, path.relative_to(source))
            shutil.copyfile(safe_source, destination)
    write_report(target, result)


def _report_card(result: Record, path: str) -> str:
    """Summarise one native backend without concealing failed comparisons."""
    counts = Counter(case["status"] for case in result["cases"])
    esc = html.escape
    status = "pass" if result.get("passed") else "fail"
    detail = " · ".join(f"{counts[key]} {key}" for key in ("pass", "warning", "fail", "error"))
    failures = [case for case in result["cases"] if case["status"] in ("error", "fail")]
    first = '<p class="muted">All interior comparisons pass.</p>'
    if failures:
        first = "<p>" + esc(case_summary(failures[0])) + "</p>"
    return (
        f'<section class="panel"><span class="badge {status}">{status}</span>'
        f'<h2><a href="./{quote(path, safe="/")}/index.html">{esc(result["backend"])}</a></h2>'
        f'<p>{esc(detail)}</p>{first}<p><a href="./{quote(path, safe="/")}/results.json">Quantitative JSON</a></p></section>'
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
    cards, names, summaries = [], set(), []
    for source, result in results:
        name = result["backend"] + "-" + result["interface"]
        if not _BACKEND_NAME.fullmatch(name) or name in names:
            raise ValueError(f"Invalid or duplicate report backend/interface: {name}")
        names.add(name)
        _copy_report(source, output / name, result)
        cards.append(_report_card(result, name))
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
        complete=complete,
        missing_reports=missing,
        coverage_known=bool(context),
        passed=complete is True and all(r["passed"] for r in summaries),
    )
    write_json(output / "site.json", manifest)
    copy_assets(output)
    _write_overview(output, manifest, cards)
    return manifest


def _write_overview(output: Path, manifest: Record, cards: list[str]) -> None:
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
    elif not manifest["coverage_known"] and cards:
        notice = '<p class="notice warning">Legacy run has no package manifest; completeness cannot be verified.</p>'
    content = header + notice + ("".join(cards) if cards else empty)
    (output / "index.html").write_text(page_document("brainhops evaluation results", content))
    (output / ".nojekyll").touch()
