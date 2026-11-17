from langchain_text_splitters import RecursiveCharacterTextSplitter

CHUNK_SIZE = 800
CHUNK_OVERLAP = 100
# Policies and JDs are cited clause by clause, so they use paragraph-sized chunks;
# an 800-char chunk held two or three policy clauses and diluted the citation.
CLAUSE_CHUNK_SIZE = 400
CLAUSE_CHUNK_OVERLAP = 0
SEPARATORS = ["\n\n", "\n", ". ", " "]


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, chunk_overlap: int = CHUNK_OVERLAP) -> list[str]:
    splitter = RecursiveCharacterTextSplitter(
        separators=SEPARATORS,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
    )
    return [chunk for chunk in splitter.split_text(text) if chunk.strip()]
