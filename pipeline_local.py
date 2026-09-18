"""Préparation documentaire locale : aucun modèle, téléchargement ou appel réseau.

PDF -> cache par page -> JSONL/CSV -> SQLite FTS5 -> rapport HTML autonome.
Les heuristiques de clauses, tableaux et obligations demandent une revue humaine.
"""
from __future__ import annotations

import csv
import hashlib
import html
import importlib.metadata
import json
import logging
import re
import sqlite3
import time
import unicodedata
import uuid
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import pdfplumber

VERSION = "1.0.0"
OBLIGATION = re.compile(
    r"\b(?:shall(?:\s+not)?|must(?:\s+not)?|doit|doivent|devra|devront|"
    r"ne\s+doit\s+pas|ne\s+doivent\s+pas|est\s+interdit|sont\s+interdits|"
    r"is\s+required\s+to|are\s+required\s+to)\b", re.I)
QUALIFIER = re.compile(r"\b(?:si|sauf|except|unless|provided|lorsque|uniquement|if|when)\b", re.I)
REFERENCE = re.compile(r"\b(?:(?:NF\s+)?EN(?:\s+ISO)?|ISO|IEC|UIC)\s*[- ]?\s*\d{2,6}(?:[-:]\d{1,4})*\b", re.I)
HEADING = re.compile(
    r"^(?P<id>(?:\d{1,2}(?:\.\d{1,3}){0,5}|[A-Z]\.\d{1,3}(?:\.\d{1,3}){0,4}))"
    r"[.)]?\s+(?P<title>[^\d\W].{2,135})$", re.UNICODE)
ANNEX = re.compile(r"^(?:annexe?|appendix)\s+(?P<id>[A-Z])\b(?P<title>.*)$", re.I)


@dataclass
class Config:
    input_dir: Path
    output_dir: Path
    # Limite du lot, pas seulement des nouvelles pages. None = tous les PDF.
    max_pages: int | None = 100
    tables: bool = True
    # "lines" recommandé ; "text" trouve aussi de faux tableaux dans la prose.
    table_strategy: str = "lines"
    min_text_chars: int = 60
    max_chunk_chars: int = 1800
    max_vector_objects_for_tables: int = 4000
    progress_every: int = 25
    retry_errors: bool = True

    def validate(self):
        self.input_dir = Path(self.input_dir).resolve()
        self.output_dir = Path(self.output_dir).resolve()
        if not self.input_dir.is_dir():
            raise FileNotFoundError(f"Dossier PDF absent : {self.input_dir}")
        if self.input_dir == self.output_dir or self.input_dir in self.output_dir.parents:
            raise ValueError("Le dossier de sortie doit être extérieur au dossier PDF.")
        if self.output_dir in self.input_dir.parents:
            raise ValueError("Le dossier PDF ne doit pas être situé dans les sorties.")
        if self.max_pages is not None and (isinstance(self.max_pages, bool) or self.max_pages < 1):
            raise ValueError("max_pages doit être un entier positif ou None.")
        if self.max_chunk_chars < 200:
            raise ValueError("max_chunk_chars doit être au moins 200.")
        if self.table_strategy not in {"lines", "text"}:
            raise ValueError("table_strategy : 'lines' ou 'text'.")
        if self.progress_every < 1:
            raise ValueError("progress_every doit être positif.")


def atomic_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def clean_text(text: str) -> str:
    """Nettoyage conservateur. Aucun retrait des notes, négations ou en-têtes."""
    text = unicodedata.normalize("NFC", text).replace("\x00", "").replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(lines).strip()


def extraction_signature(cfg: Config) -> str:
    settings = {
        "version": VERSION,
        "packages": {p: importlib.metadata.version(p) for p in ("pdfplumber", "pdfminer.six")},
        "tables": cfg.tables, "strategy": cfg.table_strategy,
        "min_text_chars": cfg.min_text_chars,
        "max_vector_objects_for_tables": cfg.max_vector_objects_for_tables,
    }
    return hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()[:20]


def discover(input_dir: Path) -> list[dict]:
    """Doublons exacts uniquement. Aucune édition similaire n'est éliminée."""
    result, seen = [], {}
    for path in sorted(input_dir.rglob("*"), key=lambda p: str(p).casefold()):
        if not path.is_file() or path.suffix.lower() != ".pdf":
            continue
        row = {"path": str(path), "relative_path": str(path.relative_to(input_dir)),
               "file_name": path.name, "status": "pending", "duplicate_of": "",
               "doc_id": "", "sha256": "", "page_count": 0, "selected_pages": 0,
               "error": "", "size_bytes": 0}
        try:
            row["size_bytes"] = path.stat().st_size
            row["sha256"] = sha256_file(path)
            row["doc_id"] = row["sha256"]
            if row["sha256"] in seen:
                row["status"] = "duplicate"
                row["duplicate_of"] = seen[row["sha256"]]
            else:
                seen[row["sha256"]] = row["relative_path"]
        except Exception as exc:
            row.update(status="file_error", error=f"{type(exc).__name__}: {exc}")
        result.append(row)
    return result


def extract_page(page, cfg: Config, doc_id: str, signature: str) -> dict:
    row = {"doc_id": doc_id, "page_pdf": page.page_number, "signature": signature,
           "status": "ok", "raw_text": "", "clean_text": "", "tables": [],
           "flags": [], "error": "", "width": float(page.width), "height": float(page.height)}
    started = time.perf_counter()
    try:
        # x/y tolerances are explicit to make the extraction reproducible.
        raw = page.extract_text(x_tolerance=3, y_tolerance=3, layout=False) or ""
        row.update(raw_text=raw, clean_text=clean_text(raw))
        row["text_chars"] = len(re.sub(r"\s", "", raw))
        row["image_count"] = len(page.images)
        row["vector_count"] = len(page.lines) + len(page.rects) + len(page.curves)
        if row["text_chars"] < cfg.min_text_chars:
            row["flags"].append("peu_de_texte_revue_scan_ou_page_vide")
        if row["image_count"]:
            row["flags"].append("images_presentes_non_interpretees")
        if row["vector_count"] > 20:
            row["flags"].append("objets_vectoriels_tableau_ou_schema_a_revoir")
        if "\ufffd" in raw or "(cid:" in raw:
            row["flags"].append("encodage_texte_suspect")
        if re.search(r"\.{4,}\s*\d+", raw):
            row["flags"].append("sommaire_possible")
        if not cfg.tables:
            row["flags"].append("extraction_tableaux_desactivee")
        elif row["vector_count"] > cfg.max_vector_objects_for_tables:
            row["flags"].append("tableaux_non_traites_page_trop_complexe")
        else:
            try:
                settings = {"vertical_strategy": cfg.table_strategy,
                            "horizontal_strategy": cfg.table_strategy}
                for num, found in enumerate(page.find_tables(settings), 1):
                    cells = found.extract(x_tolerance=3, y_tolerance=3)
                    if len(cells) < 2 or max((len(r) for r in cells), default=0) < 2:
                        continue
                    normalized = [[None if x is None else clean_text(x) for x in r] for r in cells]
                    slots = sum(len(r) for r in normalized)
                    blanks = sum(x is None or x == "" for r in normalized for x in r)
                    row["tables"].append({
                        "table_id": f"{doc_id}:p{page.page_number}:t{num}",
                        "bbox": [float(x) for x in found.bbox], "cells": normalized,
                        "rows": len(normalized), "columns": max(map(len, normalized)),
                        "empty_fraction": round(blanks / slots, 4),
                        "strategy": cfg.table_strategy, "review_status": "a_verifier",
                        "flags": ["cellules_vides_ou_fusionnees"] if blanks else [],
                    })
                if row["tables"]:
                    row["flags"].append("tableaux_extraits_a_verifier")
                if re.search(r"\b(?:tableau|table)\s+\d", raw, re.I) and not row["tables"]:
                    row["flags"].append("mention_tableau_sans_tableau_detecte")
            except Exception as exc:
                row["flags"].append("erreur_extraction_tableaux")
                row["table_error"] = f"{type(exc).__name__}: {exc}"
    except Exception as exc:
        row.update(status="page_error", error=f"{type(exc).__name__}: {exc}")
        row["flags"].append("erreur_page")
    row["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    return row


def cached_page(path: Path, doc_id: str, page_num: int, signature: str, retry_errors: bool):
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
        if (row["doc_id"], row["page_pdf"], row["signature"]) != (doc_id, page_num, signature):
            return None
        if retry_errors and (row["status"] != "ok" or "table_error" in row):
            return None
        if not isinstance(row["raw_text"], str) or not isinstance(row["tables"], list):
            return None
        return row
    except (OSError, ValueError, KeyError, TypeError):
        return None


def heading_candidate(line: str):
    if len(line) > 145 or re.search(r"\.{3,}|\b(?:doit|doivent|shall|must)\b", line, re.I):
        return None
    annex = ANNEX.match(line)
    if annex:
        return {"clause": f"Annexe {annex['id'].upper()}", "heading": line,
                "detection": "heuristique_a_confirmer"}
    match = HEADING.match(line)
    if not match:
        return None
    if re.match(r"(?:km|m|s|ms|bar|kN|N|kg|mm|Hz)\b", match["title"]):
        return None
    return {"clause": match["id"], "heading": line, "detection": "heuristique_a_confirmer"}


def split_sections(text: str, previous: dict | None, ignore_headings=False):
    """Offsets dans clean_text. Une section traversant une page garde son contexte candidat."""
    positions, offset = [], 0
    for line in text.splitlines(keepends=True):
        candidate = None if ignore_headings else heading_candidate(line.strip())
        if candidate:
            positions.append((offset, candidate))
        offset += len(line)
    sections, cursor, state = [], 0, previous
    for start, candidate in positions:
        if start > cursor:
            sections.append((cursor, start, state))
        state, cursor = candidate, start
    if cursor < len(text):
        sections.append((cursor, len(text), state))
    return sections, state


def chunks_for_page(page: dict, previous: dict | None, limit: int):
    text = page["clean_text"]
    sections, state = split_sections(text, previous, "sommaire_possible" in page["flags"])
    chunks = []
    for start, end, clause in sections:
        cursor = start
        while cursor < end:
            stop = min(cursor + limit, end)
            if stop < end:
                boundary = text.rfind("\n", cursor + limit // 2, stop)
                if boundary < 0:
                    boundary = text.rfind(" ", cursor + limit // 2, stop)
                if boundary >= 0:
                    stop = boundary + 1
            fragment = text[cursor:stop]
            if fragment.strip():
                cid = f"{page['doc_id']}:p{page['page_pdf']}:c{len(chunks)+1}"
                chunks.append({"chunk_id": cid, "doc_id": page["doc_id"], "page_pdf": page["page_pdf"],
                               "clause_candidate": clause["clause"] if clause else "",
                               "heading_candidate": clause["heading"] if clause else "",
                               "clause_status": "heuristique_a_confirmer" if clause else "non_reperee",
                               "start_char": cursor, "end_char": stop, "text": fragment,
                               "references_candidates": sorted(set(REFERENCE.findall(fragment))),
                               "table_ids": [t["table_id"] for t in page["tables"]],
                               "flags": page["flags"]})
            cursor = stop
    return chunks, state


def obligations_for_page(page: dict, chunks: list[dict]):
    """Blocs de lignes, non exigences validées. Conserve contexte et offsets source."""
    text = page["clean_text"]
    lines = text.splitlines(keepends=True)
    offsets, cursor = [], 0
    for line in lines:
        offsets.append(cursor)
        cursor += len(line)
    result = []
    for i, line in enumerate(lines):
        match = OBLIGATION.search(line)
        if not match:
            continue
        start = offsets[max(0, i - 1)]
        end = offsets[i + 3] if i + 3 < len(offsets) else len(text)
        chunk = next((c for c in chunks if c["start_char"] <= offsets[i] < c["end_char"]), None)
        context = text[start:end]
        result.append({"candidate_id": f"{page['doc_id']}:p{page['page_pdf']}:o{len(result)+1}",
                       "doc_id": page["doc_id"], "page_pdf": page["page_pdf"],
                       "clause_candidate": chunk["clause_candidate"] if chunk else "",
                       "trigger": match.group(), "text": context,
                       "start_char": start, "end_char": end,
                       "condition_or_exception_marker": bool(QUALIFIER.search(context)),
                       "status": "candidat_non_valide", "commentaire_relecteur": ""})
    return result


def excel_safe(value):
    if isinstance(value, (list, dict)):
        value = json.dumps(value, ensure_ascii=False)
    if value is None:
        return ""
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


class CsvOutput:
    def __init__(self, path, fields):
        self.stream = Path(path).open("w", encoding="utf-8-sig", newline="")
        self.writer = csv.DictWriter(self.stream, fields, delimiter=";", extrasaction="ignore")
        self.writer.writeheader()

    def write(self, row):
        self.writer.writerow({k: excel_safe(v) for k, v in row.items()})

    def close(self):
        self.stream.close()


def load_metadata(path: Path | None) -> dict:
    if path is None:
        return {}
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f, delimiter=";"))
    result = {}
    for row in rows:
        key = row.get("relative_path", "").replace("\\", "/")
        if not key:
            continue
        if key in result:
            raise ValueError(f"Métadonnées dupliquées pour {key}")
        result[key] = {k: row.get(k, "") for k in ("reference", "edition", "language", "document_status")}
    return result


def create_index(path: Path):
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE chunks (chunk_id TEXT PRIMARY KEY, doc_id TEXT, file_name TEXT, "
               "page_pdf INTEGER, clause TEXT, edition TEXT, text TEXT)")
    try:
        db.execute("CREATE VIRTUAL TABLE search_fts USING fts5(chunk_id UNINDEXED, text, "
                   "tokenize='unicode61 remove_diacritics 2')")
        mode = "FTS5"
    except sqlite3.OperationalError:
        mode = "LIKE"
    db.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT)")
    db.execute("INSERT INTO settings VALUES ('mode', ?)", (mode,))
    return db, mode


def search(run_dir: Path, query: str, limit=20, doc_id: str | None = None, mode="all"):
    """Recherche littérale locale. AND par défaut, OR avec mode='any'."""
    if mode not in {"all", "any"}:
        raise ValueError("mode doit être 'all' ou 'any'.")
    tokens = re.findall(r"\w+", query, re.UNICODE)[:30]
    if not tokens:
        return []
    index = Path(run_dir) / "search.sqlite"
    if not index.is_file():
        raise FileNotFoundError(index)
    db = sqlite3.connect(index)
    db.row_factory = sqlite3.Row
    try:
        engine = db.execute("SELECT value FROM settings WHERE key='mode'").fetchone()[0]
        if engine == "FTS5":
            expression = (" AND " if mode == "all" else " OR ").join('"' + t + '"' for t in tokens)
            sql = ("SELECT c.*, bm25(search_fts) AS score FROM search_fts "
                   "JOIN chunks c ON c.chunk_id=search_fts.chunk_id WHERE search_fts MATCH ?")
            params = [expression]
            if doc_id:
                sql += " AND c.doc_id=?"
                params.append(doc_id)
            sql += " ORDER BY score, c.chunk_id LIMIT ?"
        else:
            clauses = ["text LIKE ? ESCAPE '\\'" for _ in tokens]
            sql = "SELECT *, 0 AS score FROM chunks WHERE (" + (" AND " if mode == "all" else " OR ").join(clauses) + ")"
            params = ["%" + t.replace("_", "\\_") + "%" for t in tokens]
            if doc_id:
                sql += " AND doc_id=?"
                params.append(doc_id)
            sql += " ORDER BY chunk_id LIMIT ?"
        params.append(max(1, min(int(limit), 200)))
        return [dict(r) for r in db.execute(sql, params)]
    finally:
        db.close()


def render_page(pdf_path: Path, page_pdf: int, destination: Path, resolution=110):
    """Image de revue à la demande, sans OCR. Aucune prévisualisation massive par défaut."""
    with pdfplumber.open(pdf_path) as pdf:
        if not 1 <= page_pdf <= len(pdf.pages):
            raise ValueError("Numéro de page PDF hors limites.")
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        pdf.pages[page_pdf - 1].to_image(resolution=resolution).save(str(destination))
    return destination


def read_jsonl(path, limit=20):
    rows = []
    with Path(path).open(encoding="utf-8") as f:
        for line in f:
            rows.append(json.loads(line))
            if len(rows) >= limit:
                break
    return rows


def html_table(rows, fields=None, limit=20):
    rows = list(rows)[:limit]
    if not rows:
        return "<p>Aucun résultat.</p>"
    fields = fields or list(rows[0])
    head = "".join(f"<th>{html.escape(str(k))}</th>" for k in fields)
    body = "".join("<tr>" + "".join(f"<td>{html.escape(str(r.get(k, '')))}</td>" for k in fields) + "</tr>" for r in rows)
    return '<div style="overflow:auto"><table><thead><tr>' + head + "</tr></thead><tbody>" + body + "</tbody></table></div>"


def write_report(run_dir, summary, inventory, review_sample):
    cards = "".join(f"<div class='card'><strong>{html.escape(str(v))}</strong><span>{html.escape(k)}</span></div>"
                    for k, v in [("PDF uniques traités", summary["documents_processed"]),
                                 ("Pages sélectionnées", summary["pages_selected"]),
                                 ("Pages en erreur", summary["pages_error"]),
                                 ("Tableaux candidats", summary["tables"]),
                                 ("Blocs d’obligation", summary["obligations_candidates"]),
                                 ("Pages issues du cache", summary["pages_cached"])])
    flags = [{"signal": k, "pages": v} for k, v in summary["flags"].items()]
    body = f"""<!doctype html><html lang="fr"><meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Qualité du corpus freinage</title><style>
    body{{font:16px/1.55 Segoe UI,Arial,sans-serif;color:#243746;background:#f4f6f8;margin:0}}
    main{{max-width:1180px;margin:auto;padding:36px}}h1{{font-size:32px}}h2{{margin-top:36px}}
    .cards{{display:flex;flex-wrap:wrap;gap:12px}}.card{{background:white;padding:20px;min-width:145px;border-radius:9px}}
    .card strong{{display:block;font-size:28px;color:#284b63}}.card span{{font-size:14px}}
    table{{border-collapse:collapse;width:100%;background:white}}td,th{{padding:10px;border:1px solid #d9e0e5;text-align:left;vertical-align:top;white-space:pre-wrap;overflow-wrap:anywhere}}
    th{{background:#284b63;color:white}}.note{{padding:16px;background:#fff4d8;border-radius:8px}}
    code{{background:#e7edf2;padding:2px 5px}}a{{color:#284b63}}</style><main>
    <p>TRAITEMENT DOCUMENTAIRE LOCAL • {html.escape(summary['run_id'])}</p>
    <h1>Rapport qualité du corpus freinage</h1><div class="cards">{cards}</div>
    <p class="note">Ce rapport mesure le traitement, pas la conformité ni l’exhaustivité normative.
    Les tableaux, clauses et obligations sont des candidats à revoir. Les graphiques et schémas ne sont pas interprétés.</p>
    <h2>Périmètre de cette exécution</h2>
    <p>Limite de pages : {html.escape(str(summary['max_pages']))}. PDF différés par la limite : {summary['documents_deferred']}.
    Doublons exacts : {summary['duplicates']}. Fichiers en erreur : {summary['files_error']}.
    Moteur de recherche : {summary['search_mode']}. Durée : {summary['elapsed_seconds']} s.</p>
    <p>La limite sélectionne les premières pages des PDF triés : ce lot n’est pas un échantillon aléatoire représentatif.
    Les compteurs de pages excluent les fichiers impossibles à ouvrir. Consulter leur liste ci-dessous.</p>
    <h2>Signaux à examiner</h2>{html_table(flags, limit=100)}
    <p>Un faible volume de texte peut désigner une page vide, une couverture, un schéma ou un scan.
    Des objets vectoriels peuvent être un tableau, un logo ou un dessin. Aucun de ces signaux n’est une classification certaine.</p>
    <h2>Inventaire</h2>{html_table(inventory, ['relative_path','status','page_count','selected_pages','edition','error'], limit=100)}
    <p>Affichage limité à 100 fichiers. Liste complète : <a href="inventory.csv">inventory.csv</a>.</p>
    <h2>Échantillon des pages à revoir</h2>{html_table(review_sample, limit=30)}
    <p>Liste complète : <a href="review_pages.csv">review_pages.csv</a>. La page indiquée est toujours la position PDF, comptée à partir de 1.</p>
    <h2>Livrables</h2><ul>
    <li><a href="pages.jsonl">pages.jsonl</a> : texte brut et nettoyé, position PDF, signaux et tableaux.</li>
    <li><a href="chunks.jsonl">chunks.jsonl</a> : fragments avec offsets et clauses candidates.</li>
    <li><a href="obligations_candidates.csv">obligations_candidates.csv</a> : blocs de texte à qualifier.</li>
    <li><a href="tables.csv">tables.csv</a> : inventaire et chemins des tableaux individuels.</li>
    <li><a href="repeated_margins.csv">repeated_margins.csv</a> : premières et dernières lignes répétées, conservées.</li>
    <li><a href="summary.json">summary.json</a> et <a href="manifest.json">manifest.json</a> : compteurs et paramètres.</li>
    </ul><h2>Contrôle humain conseillé</h2><p>Comparer le texte et les tableaux à la page d’origine, vérifier unités,
    cellules fusionnées, notes et exceptions, puis valider les clauses. Une absence de résultat de recherche ne prouve pas
    l’absence d’une exigence. Les versions sont à renseigner dans les métadonnées.</p></main></html>"""
    (run_dir / "rapport_qualite.html").write_text(body, encoding="utf-8")


def export_run(cfg, run_dir, inventory, signature, stats, started):
    """Écriture en flux ; seuls l'index SQLite et le cache contiennent le corpus entier."""
    metadata_fields = ["file_name", "relative_path", "reference", "edition", "language", "document_status"]
    inventory_csv = CsvOutput(run_dir / "inventory.csv", ["doc_id", "relative_path", "file_name", "size_bytes",
        "sha256", "status", "duplicate_of", "page_count", "selected_pages", "error", *metadata_fields[2:]])
    for row in inventory:
        inventory_csv.write(row)
    inventory_csv.close()
    review = CsvOutput(run_dir / "review_pages.csv", ["doc_id", "file_name", "page_pdf", "status", "flags", "error", "table_error"])
    tables_csv = CsvOutput(run_dir / "tables.csv", ["table_id", "doc_id", "file_name", "page_pdf", "rows", "columns",
        "empty_fraction", "bbox", "strategy", "csv_path", "review_status", "flags"])
    obligations_csv = CsvOutput(run_dir / "obligations_candidates.csv", ["candidate_id", "doc_id", "file_name", "page_pdf",
        "edition", "clause_candidate", "trigger", "text", "start_char", "end_char", "condition_or_exception_marker", "status", "commentaire_relecteur"])
    repeated = CsvOutput(run_dir / "repeated_margins.csv", ["doc_id", "file_name", "position", "text", "pages_count", "action"])
    db, search_mode = create_index(run_dir / "search.sqlite")
    counters = Counter()
    flag_counts, review_sample = Counter(), []
    try:
        with (run_dir / "pages.jsonl").open("w", encoding="utf-8") as pages_out, \
             (run_dir / "chunks.jsonl").open("w", encoding="utf-8") as chunks_out, \
             (run_dir / "tables.jsonl").open("w", encoding="utf-8") as tables_out, \
             (run_dir / "obligations_candidates.jsonl").open("w", encoding="utf-8") as obligations_out:
            for doc in inventory:
                if doc["status"] not in {"processed", "partial"}:
                    continue
                state, margins = None, Counter()
                for num in range(1, doc["selected_pages"] + 1):
                    cache_file = cfg.output_dir / "cache" / signature / doc["doc_id"] / f"page_{num:06d}.json"
                    page = json.loads(cache_file.read_text(encoding="utf-8"))
                    page.update({k: doc.get(k, "") for k in metadata_fields})
                    # Printed pagination is intentionally not guessed.
                    page["printed_page"] = None
                    counters["pages_selected"] += 1
                    counters["pages_error"] += page["status"] != "ok"
                    flag_counts.update(page["flags"])
                    pages_out.write(json.dumps(page, ensure_ascii=False) + "\n")
                    if page["flags"] or page["status"] != "ok":
                        review.write(page)
                        if len(review_sample) < 30:
                            review_sample.append({k: page.get(k, "") for k in ("file_name", "page_pdf", "flags", "error")})
                    lines = [x for x in page["clean_text"].splitlines() if x.strip()]
                    if lines:
                        margins[("haut", lines[0])] += 1
                        margins[("bas", lines[-1])] += 1
                    if page["status"] != "ok" or "peu_de_texte_revue_scan_ou_page_vide" in page["flags"]:
                        state = None  # Unknown intervening content: do not carry a stale clause.
                    chunks, state = chunks_for_page(page, state, cfg.max_chunk_chars)
                    for chunk in chunks:
                        chunk.update({k: doc.get(k, "") for k in metadata_fields})
                        chunks_out.write(json.dumps(chunk, ensure_ascii=False) + "\n")
                        db.execute("INSERT INTO chunks VALUES (?,?,?,?,?,?,?)", (
                            chunk["chunk_id"], doc["doc_id"], doc["file_name"], num,
                            chunk["clause_candidate"], doc.get("edition", ""), chunk["text"]))
                        if search_mode == "FTS5":
                            db.execute("INSERT INTO search_fts VALUES (?,?)", (chunk["chunk_id"], chunk["text"]))
                        counters["chunks"] += 1
                    for candidate in obligations_for_page(page, chunks):
                        candidate.update({k: doc.get(k, "") for k in metadata_fields})
                        obligations_out.write(json.dumps(candidate, ensure_ascii=False) + "\n")
                        obligations_csv.write(candidate)
                        counters["obligations_candidates"] += 1
                    for j, t in enumerate(page["tables"], 1):
                        t = dict(t, doc_id=doc["doc_id"], page_pdf=num, file_name=doc["file_name"], edition=doc.get("edition", ""))
                        relative = Path("tables") / doc["doc_id"] / f"p{num:06d}_t{j:03d}.csv"
                        target = run_dir / relative
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with target.open("w", encoding="utf-8-sig", newline="") as stream:
                            writer = csv.writer(stream, delimiter=";")
                            writer.writerows([[excel_safe(c) for c in row] for row in t["cells"]])
                        t["csv_path"] = relative.as_posix()
                        tables_out.write(json.dumps(t, ensure_ascii=False) + "\n")
                        tables_csv.write(t)
                        counters["tables"] += 1
                    if num % 100 == 0:
                        db.commit()
                for (position, text), count in margins.items():
                    if count >= 3:
                        repeated.write({"doc_id": doc["doc_id"], "file_name": doc["file_name"], "position": position,
                                        "text": text, "pages_count": count, "action": "conserve_revue_manuelle"})
        db.commit()
    finally:
        db.close()
        for stream in (review, tables_csv, obligations_csv, repeated):
            stream.close()
    summary = {"run_id": run_dir.name, "pipeline_version": VERSION, "max_pages": cfg.max_pages,
               "files_found": len(inventory), "documents_processed": sum(d["status"] in {"processed", "partial"} for d in inventory),
               "duplicates": sum(d["status"] == "duplicate" for d in inventory),
               "documents_deferred": sum(d["status"] == "deferred_limit" for d in inventory),
               "files_error": sum(d["status"] == "file_error" for d in inventory),
               "pages_cached": stats["cached"], "pages_extracted": stats["extracted"],
               "search_mode": search_mode, "flags": dict(flag_counts),
               "elapsed_seconds": round(time.perf_counter() - started, 2)}
    summary.update({k: counters[k] for k in ("pages_selected", "pages_error", "chunks", "tables", "obligations_candidates")})
    atomic_json(run_dir / "summary.json", summary)
    write_report(run_dir, summary, inventory, review_sample)
    return summary


def run_pipeline(cfg: Config, metadata_csv: Path | None = None,
                 progress: Callable[[str], None] = print) -> Path:
    """Un seul traitement à la fois par dossier output. Ctrl+C puis relancer pour reprendre."""
    cfg.validate()
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    lock_path = cfg.output_dir / "pipeline.lock"
    try:
        lock_fd = lock_path.open("x", encoding="utf-8")
    except FileExistsError:
        raise RuntimeError("Un traitement utilise ce dossier (pipeline.lock). Après un arrêt brutal, "
                           "vérifier qu'aucun traitement ne tourne avant de retirer ce fichier.") from None
    try:
        lock_fd.write(datetime.now(timezone.utc).isoformat())
        lock_fd.close()
        return _run(cfg, metadata_csv, progress)
    finally:
        lock_fd.close()
        lock_path.unlink(missing_ok=True)


def _run(cfg, metadata_csv, progress):
    started = time.perf_counter()
    signature = extraction_signature(cfg)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:6]
    run_dir = cfg.output_dir / "runs" / run_id
    run_dir.mkdir(parents=True)
    handler = logging.FileHandler(run_dir / "execution.log", encoding="utf-8")
    logger = logging.getLogger(f"freinage.{run_id}")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.addHandler(handler)
    def log(message):
        logger.info(message)
        progress(message)
    manifest = {"run_id": run_id, "status": "running", "version": VERSION,
                "signature": signature, "config": {k: str(v) if isinstance(v, Path) else v for k, v in asdict(cfg).items()},
                "packages": {x: importlib.metadata.version(x) for x in ("pdfplumber", "pdfminer.six", "pypdfium2")}}
    inventory, stats = [], Counter()
    try:
        metadata = load_metadata(metadata_csv)
        log("Inventaire et empreintes SHA-256 des fichiers…")
        inventory = discover(cfg.input_dir)
        if not inventory:
            raise ValueError(f"Aucun PDF dans {cfg.input_dir}. Ajouter des fichiers puis relancer.")
        used = 0
        for doc in inventory:
            doc.update(metadata.get(doc["relative_path"].replace("\\", "/"), {}))
            if doc["status"] != "pending":
                continue
            if cfg.max_pages is not None and used >= cfg.max_pages:
                doc["status"] = "deferred_limit"
                continue
            path = Path(doc["path"])
            try:
                with pdfplumber.open(path) as pdf:
                    doc["page_count"] = len(pdf.pages)
                    n = len(pdf.pages) if cfg.max_pages is None else min(len(pdf.pages), cfg.max_pages - used)
                    doc["selected_pages"] = n
                    # The original PDF metadata are not treated as validated edition data.
                    doc["pdf_metadata"] = {k: str(v) for k, v in pdf.metadata.items()}
                    log(f"{doc['relative_path']} : {n}/{len(pdf.pages)} pages sélectionnées")
                    for index in range(n):
                        page_num = index + 1
                        cache = cfg.output_dir / "cache" / signature / doc["doc_id"] / f"page_{page_num:06d}.json"
                        row = cached_page(cache, doc["doc_id"], page_num, signature, cfg.retry_errors)
                        if row is not None:
                            stats["cached"] += 1
                        else:
                            page = pdf.pages[index]
                            try:
                                row = extract_page(page, cfg, doc["doc_id"], signature)
                                atomic_json(cache, row)
                            finally:
                                page.close()  # Release pdfminer layout caches after each page.
                            stats["extracted"] += 1
                        used += 1
                        if used % cfg.progress_every == 0:
                            log(f"{used} pages traitées | nouvelles {stats['extracted']} | cache {stats['cached']}")
                    doc["status"] = "processed" if n == len(pdf.pages) else "partial"
                if sha256_file(path) != doc["sha256"]:
                    raise RuntimeError("PDF modifié pendant le traitement : exclu de cette exécution. Relancer sur une copie stable.")
            except Exception as exc:
                doc.update(status="file_error", error=f"{type(exc).__name__}: {exc}")
                log(f"Fichier ignoré : {doc['relative_path']} — {doc['error']}")
        manifest.update(inventory=inventory, status="exporting")
        atomic_json(run_dir / "manifest.json", manifest)
        log("Exports, découpage, repérage des obligations et index de recherche…")
        summary = export_run(cfg, run_dir, inventory, signature, stats, started)
        # 'completed' describes the run, not the completeness or quality of the corpus.
        manifest.update(status="completed", summary=summary)
        atomic_json(run_dir / "manifest.json", manifest)
        atomic_json(cfg.output_dir / "latest_run.json", {"run_dir": str(run_dir)})
        log(f"Terminé : {summary['pages_selected']} pages exportées ; rapport dans {run_dir}")
        return run_dir
    except BaseException as exc:
        manifest.update(status="interrupted" if isinstance(exc, KeyboardInterrupt) else "failed",
                        error=f"{type(exc).__name__}: {exc}", inventory=inventory)
        atomic_json(run_dir / "manifest.json", manifest)
        logger.exception("Traitement interrompu ou échoué ; le cache des pages est conservé.")
        raise
    finally:
        logger.removeHandler(handler)
        handler.close()
