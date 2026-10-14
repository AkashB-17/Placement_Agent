from langchain_text_splitters import RecursiveCharacterTextSplitter

CHUNK_SIZE = 800
CHUNK_OVERLAP = 100
SEPARATORS = ["\n\n", "\n", ". ", " "]


def chunk_text(text: str) -> list[str]:
    splitter = RecursiveCharacterTextSplitter(
        separators=SEPARATORS,
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        length_function=len,
    )
    return [chunk for chunk in splitter.split_text(text) if chunk.strip()]
