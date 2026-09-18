"""Fixtures synthétiques, sans texte de réglementation réelle."""
from pathlib import Path
from io import BytesIO

from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import reportlab
from PIL import Image, ImageDraw, ImageFont

pdfmetrics.registerFont(TTFont("DemoVera", str(Path(reportlab.__file__).parent / "fonts/Vera.ttf")))


def create_demo(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(path), pagesize=(595, 842))
    c.setTitle("Demonstration fictive freinage - aucune norme reelle")
    def frame(n):
        c.setFont("DemoVera", 8)
        c.drawString(40, 810, "DOCUMENT FICTIF - ESSAI DU PIPELINE - NE PAS UTILISER EN CONCEPTION")
        c.drawString(40, 25, f"Demo | page imprimee {n + 10}")
    frame(1)
    lines = ["1 Objet", "Ce document sert uniquement aux tests de lecture des PDF.",
             "2.1 Freinage de service", "Le dossier doit contenir une justification documentee.",
             "Cette phrase est un exemple fictif et ne fixe aucun seuil de securite.",
             "2.2 Condition particuliere", "Si la configuration change, le rapport ne doit pas etre reutilise sans revue.",
             "Les references ISO 12345 et EN 54321 sont fictives dans ce document."]
    y = 765
    for line in lines:
        c.setFont("DemoVera", 10); c.drawString(40, y, line); y -= 27
    c.showPage()
    frame(2)
    c.setFont("DemoVera", 10)
    c.drawString(40, 765, "3 Tableau de demonstration")
    c.drawString(40, 738, "Tableau 1 : donnees synthetiques, aucune valeur normative.")
    xs, ys = [40, 230, 390, 550], [700, 665, 630, 595]
    for x in xs: c.line(x, ys[-1], x, ys[0])
    for y in ys: c.line(xs[0], y, xs[-1], y)
    rows = [["Champ", "Valeur fictive", "Remarque"], ["Exemple A", "12", "A verifier"],
            ["Exemple B", "=1+1", "Texte non execute"]]
    for ri, row in enumerate(rows):
        for ci, text in enumerate(row):c.drawString(xs[ci] + 8, ys[ri] - 23, text)
    c.drawString(40, 555, "The reviewer shall verify the source table before using its contents.")
    c.showPage()
    frame(3)
    c.setFont("DemoVera", 10)
    c.drawString(40, 765, "4 Schema fictif")
    c.drawString(40, 738, "Les formes suivantes ne sont pas interpretees par le pipeline.")
    for i in range(24):
        c.circle(70 + (i % 8) * 62, 620 - (i // 8) * 65, 18)
    c.showPage()
    # A raster-only page emulates a scan: there is no searchable text layer.
    im = Image.new("RGB", (900, 1000), "white")
    ImageDraw.Draw(im).text((50, 80), "PAGE IMAGE FICTIVE\nAUCUNE COUCHE TEXTE", fill="black", font=ImageFont.load_default(size=30))
    buf = BytesIO(); im.save(buf, format="PNG"); buf.seek(0)
    c.drawImage(ImageReader(buf), 30, 100, width=530, height=590)
    c.showPage(); c.save()
    return path


def create_large(path: Path, pages=5000):
    c = canvas.Canvas(str(path), pagesize=(595, 842))
    for n in range(pages):
        c.setFont("Helvetica", 11)
        c.drawString(40, 780, "CORPUS SYNTHETIQUE DE CHARGE - AUCUNE VALEUR NORMATIVE")
        c.drawString(40, 740, "1.1 Freinage fictif")
        c.drawString(40, 710, f"Le rapport doit conserver la reference de la page {n + 1}.")
        c.drawString(40, 680, "Ce texte sert a mesurer le traitement sequentiel et la reprise du cache.")
        if n % 100 == 0:
            for x in [40, 220, 400]:c.line(x, 510, x, 600)
            for y in [510, 540, 570, 600]:c.line(40, y, 400, y)
            c.drawString(50, 578, "Champ");c.drawString(230, 578, "Valeur fictive")
            c.drawString(50, 548, "A");c.drawString(230, 548, "1")
            c.drawString(50, 518, "B");c.drawString(230, 518, "2")
        c.showPage()
    c.save()


if __name__ == "__main__":
    create_demo(Path(__file__).resolve().parents[1] / "data/demo/Demonstration_fictive.pdf")
