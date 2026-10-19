from io import BytesIO

from fastapi import HTTPException, UploadFile
from pypdf import PdfReader
from pypdf.errors import PdfReadError

SUPPORTED_EXTENSIONS = (".pdf", ".txt")


def extract_pdf_text(data: bytes) -> str:
    try:
        reader = PdfReader(BytesIO(data))
        pages = [(page.extract_text() or "") for page in reader.pages]
        return "\n\n".join(pages).strip()
    except PdfReadError as exc:
        raise HTTPException(status_code=422, detail="Invalid or corrupt PDF.") from exc
    except Exception as exc:
        # pypdf raises assorted non-PdfReadError exceptions on malformed input.
        raise HTTPException(status_code=422, detail="Could not parse PDF.") from exc


def text_from_upload(filename: str | None, data: bytes) -> str:
    name = (filename or "").lower()
    if name.endswith(".pdf"):
        return extract_pdf_text(data)
    if name.endswith(".txt"):
        try:
            return data.decode("utf-8").strip()
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=422, detail="File is not valid UTF-8 text.") from exc
    raise HTTPException(
        status_code=415,
        detail=f"Unsupported file type. Upload one of: {', '.join(SUPPORTED_EXTENSIONS)}.",
    )


async def resolve_source_text(text: str | None, file: UploadFile | None) -> str:
    """Return the document text from exactly one of `text` or `file`.

    An empty upload (Swagger sends one when no file is picked) counts as no file.
    Supplying both is rejected rather than silently preferring one.
    """
    data = await file.read() if file is not None else b""
    has_file = bool(data)
    has_text = bool(text and text.strip())

    if has_file and has_text:
        raise HTTPException(status_code=422, detail="Provide either text or a file, not both.")
    if has_file:
        extracted = text_from_upload(file.filename, data)
        if not extracted:
            raise HTTPException(
                status_code=422,
                detail="Could not extract text from the uploaded file.",
            )
        return extracted
    if has_text:
        return text.strip()
    raise HTTPException(status_code=400, detail="Provide either text or a file.")
