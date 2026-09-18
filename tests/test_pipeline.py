"""Tests locaux. Exécuter depuis la racine : python -m unittest discover -s tests -v"""
import json
import shutil
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pipeline_local import (Config, run_pipeline, search, read_jsonl, clean_text,
                            chunks_for_page, excel_safe, VERSION)
from create_demo import create_demo


class PipelineTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.input = self.root / "entrée avec espaces"
        self.input.mkdir()
        self.pdf = create_demo(self.input / "freins été.PDF")
        self.cfg = Config(self.input, self.root / "sorties", max_pages=None, progress_every=1)
        # The core must not make network requests, including during extraction.
        self.net1 = patch.object(socket.socket, "connect", side_effect=AssertionError("NETWORK_FORBIDDEN"))
        self.net2 = patch.object(socket, "getaddrinfo", side_effect=AssertionError("DNS_FORBIDDEN"))
        self.net1.start();self.net2.start()

    def tearDown(self):
        self.net1.stop();self.net2.stop();self.temp.cleanup()

    def run_local(self):
        return run_pipeline(self.cfg, progress=lambda _: None)

    def test_extraction_provenance_tables_and_search(self):
        run = self.run_local()
        pages = read_jsonl(run / "pages.jsonl", 100)
        self.assertEqual(len(pages), 4)
        self.assertEqual(pages[0]["page_pdf"], 1)
        self.assertIsNone(pages[0]["printed_page"])
        self.assertIn("ne doit pas", pages[0]["raw_text"])
        self.assertIn("images_presentes_non_interpretees", pages[3]["flags"])
        self.assertIn("peu_de_texte_revue_scan_ou_page_vide", pages[3]["flags"])
        self.assertEqual(len(pages[1]["tables"]), 1)
        self.assertEqual(pages[1]["tables"][0]["cells"][2][1], "=1+1")
        table_path = next((run / "tables").rglob("*.csv"))
        self.assertIn("'=1+1", table_path.read_text(encoding="utf-8-sig"))
        hits = search(run, "freinage service")
        self.assertTrue(hits)
        self.assertEqual(hits[0]["page_pdf"], 1)
        self.assertTrue(search(run, "justification"))
        self.assertEqual(search(run, "xyzabsent"), [])
        candidates = read_jsonl(run / "obligations_candidates.jsonl", 100)
        self.assertTrue(any("ne doit pas" in x["text"] for x in candidates))
        self.assertTrue(all(x["status"] == "candidat_non_valide" for x in candidates))
        for c in read_jsonl(run / "chunks.jsonl", 100):
            source = pages[c["page_pdf"] - 1]["clean_text"]
            self.assertEqual(source[c["start_char"]:c["end_char"]], c["text"])

    def test_resume_and_corrupt_cache(self):
        self.run_local()
        second = self.run_local()
        summary = json.loads((second / "summary.json").read_text())
        self.assertEqual(summary["pages_cached"], 4)
        self.assertEqual(summary["pages_extracted"], 0)
        next((self.cfg.output_dir / "cache").rglob("page_000001.json")).write_text("{bad", encoding="utf-8")
        third = self.run_local()
        summary = json.loads((third / "summary.json").read_text())
        self.assertEqual(summary["pages_extracted"], 1)

    def test_limit_duplicate_bad_pdf_and_fresh_index(self):
        shutil.copy(self.pdf, self.input / "copie.pdf")
        (self.input / "cassé.pdf").write_bytes(b"not a pdf")
        self.cfg.max_pages = 2
        run = self.run_local()
        summary = json.loads((run / "summary.json").read_text())
        self.assertEqual(summary["pages_selected"], 2)
        self.assertEqual(summary["duplicates"], 1)
        self.assertEqual(summary["files_error"], 1)
        # Changed input replaces the search corpus for the next run, with no stale records.
        for path in self.input.iterdir():path.unlink()
        create_demo(self.input / "nouveau.pdf")
        self.cfg.max_pages = 1
        next_run = self.run_local()
        self.assertTrue(all(x["page_pdf"] == 1 for x in search(next_run, "doit")))
        self.assertEqual(search(next_run, "reviewer"), [])

    def test_interrupt_and_resume(self):
        def interrupt(message):
            if "1 pages traitées" in message:raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            run_pipeline(self.cfg, progress=interrupt)
        self.assertFalse((self.cfg.output_dir / "pipeline.lock").exists())
        run = self.run_local()
        summary = json.loads((run / "summary.json").read_text())
        self.assertEqual(summary["pages_cached"], 1)
        self.assertEqual(summary["pages_selected"], 4)

    def test_settings_invalidate_cache(self):
        self.run_local()
        self.cfg.tables = False
        run = self.run_local()
        summary = json.loads((run / "summary.json").read_text())
        self.assertEqual(summary["pages_cached"], 0)
        self.assertEqual(summary["tables"], 0)

    def test_empty_input_and_lock(self):
        self.pdf.unlink()
        with self.assertRaisesRegex(ValueError, "Aucun PDF"):self.run_local()
        self.assertFalse((self.cfg.output_dir / "pipeline.lock").exists())
        (self.cfg.output_dir / "pipeline.lock").write_text("running")
        with self.assertRaisesRegex(RuntimeError, "Un traitement"):self.run_local()

    def test_chunk_no_loss_and_conservative_cleaning(self):
        text = "1 Objet\n" + ("Le système ne doit pas perdre les exceptions, sauf mention. " * 200)
        page = {"doc_id": "test", "page_pdf": 1, "clean_text": text, "flags": [], "tables": []}
        chunks, _ = chunks_for_page(page, None, 250)
        self.assertEqual("".join(x["text"] for x in chunks), text)
        self.assertTrue(all(len(x["text"]) <= 250 for x in chunks))
        self.assertIn("ne doit pas", clean_text("ne\u00a0doit pas"))
        self.assertEqual(excel_safe("=SUM(A1)"), "'=SUM(A1)")


if __name__ == "__main__":unittest.main()
