"""Generate journey fixtures: a paged UZ PDF, a RU DOCX and a corrupt PDF."""

from __future__ import annotations

import sys
from pathlib import Path

from docx import Document
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[2]
UZ_PAGES = [
    "Orol dengizi 1960-yildan boshlab qurib bormoqda. Amudaryo va Sirdaryo suvlari "
    "sug‘orishga yo‘naltirilgani sababli dengizga quyiladigan oqim keskin kamaydi.",
    "2010-yilga kelib dengiz sathi dastlabki hajmining taxminan o‘ndan bir qismiga "
    "tushdi. Tuzli changlar atrofdagi aholining sog‘lig‘iga salbiy ta’sir ko‘rsatdi.",
    "Qoraqalpog‘istonda saksovul ekish orqali qurigan tubni mustahkamlash ishlari "
    "olib borilmoqda. Bu choralar chang bo‘ronlarini kamaytirishga qaratilgan.",
]
RU_PARAGRAPHS = [
    "Аральское море начало пересыхать в 1960-х годах из-за забора воды на орошение.",
    "Северный Арал частично восстановлен после строительства Кокаральской плотины в 2005 году.",
]


def write_fixtures(target: Path) -> dict[str, Path]:
    """Write the three files and return their paths by role."""

    target.mkdir(parents=True, exist_ok=True)
    pdfmetrics.registerFont(TTFont("Plex", str(ROOT / "fonts" / "IBMPlexSerif-Regular.ttf")))
    pdf_path = target / "orol-dengizi-tarixi.pdf"
    page = canvas.Canvas(str(pdf_path), pagesize=A4)
    for text in UZ_PAGES:
        page.setFont("Plex", 12)
        text_object = page.beginText(60, 780)
        for index in range(0, len(text), 80):
            text_object.textLine(text[index : index + 80])
        page.drawText(text_object)
        page.showPage()
    page.save()

    docx_path = target / "аральское-море.docx"
    document = Document()
    for paragraph in RU_PARAGRAPHS:
        document.add_paragraph(paragraph)
    document.save(str(docx_path))

    broken_path = target / "buzilgan-manba.pdf"
    broken_path.write_bytes(b"%PDF-1.7\n" + b"\x00\xff" * 4096 + b"\n%%EOF")
    return {"pdf": pdf_path, "docx": docx_path, "broken": broken_path}


if __name__ == "__main__":
    for role, path in write_fixtures(Path(sys.argv[1])).items():
        print(role, path)
