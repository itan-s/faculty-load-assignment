import fitz  # PyMuPDF

def extract_pdf_text(path: str) -> str:
    doc = fitz.open(path)
    return "\n".join(page.get_text() for page in doc)

if __name__ == "__main__":
    print(extract_pdf_text("data/raw/workload_policy.pdf")[:500])
