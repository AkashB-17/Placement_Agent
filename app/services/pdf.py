from io import BytesIO

from fastapi import HTTPException, UploadFile
from pypdf import PdfReader


def extract_pdf_text(data: bytes) -> str:
    reader = PdfReader(BytesIO(data))
    pages = [(page.extract_text() or "") for page in reader.pages]
    return "\n\n".join(pages).strip()


def text_from_upload(filename: str | None, data: bytes) -> str:
    name = (filename or "").lower()
    if name.endswith(".pdf"):
        return extract_pdf_text(data)
    return data.decode("utf-8").strip()


async def resolve_source_text(text: str | None, file: UploadFile | None) -> str:
    if file is not None:
        data = await file.read()
        if data:
            extracted = text_from_upload(file.filename, data)
            if not extracted:
                raise HTTPException(
                    status_code=422,
                    detail="Could not extract text from the uploaded file.",
                )
            return extracted
    if text and text.strip():
        return text.strip()
    raise HTTPException(status_code=400, detail="Provide either text or a file.")
