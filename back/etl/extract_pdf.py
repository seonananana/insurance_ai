import fitz
from pathlib import Path

RAW_DIR = Path("data/raw")
TEXT_DIR = Path("data/text")

def extract_pdf(infile: Path, outfile: Path):
    doc = fitz.open(infile)
    text = "\n".join(page.get_text("text") for page in doc)
    outfile.parent.mkdir(parents=True, exist_ok=True)
    outfile.write_text(text, encoding="utf-8")

if __name__ == "__main__":
    for pdf in RAW_DIR.rglob("*.pdf"):
        txt = TEXT_DIR / pdf.relative_to(RAW_DIR)
        txt = txt.with_suffix(".txt")
        extract_pdf(pdf, txt)
