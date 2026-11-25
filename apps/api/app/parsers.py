"""Bounded, source-aware text extraction for supported knowledge documents."""
from __future__ import annotations

import io
import re
import unicodedata
import zipfile
from pathlib import Path

from docx import Document
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from pypdf import PdfReader

from .domain.knowledge import ParsedEntry as ParsedEntry  # Preserve the public parser import.
from .domain.language import Language
from .textnorm import normalize

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".txt", ".md"}
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 80 * 1024 * 1024
MAX_PAGES = 250
MAX_SHEETS = 120
MAX_ROWS_PER_SHEET = 20_000
MAX_ITEMS = 30_000

QUESTION_NAMES = {"question", "questions", "pregunta", "preguntas", "interview question"}
ANSWER_NAMES = {"answer", "answers", "respuesta", "respuestas", "suggested answer"}


def _header_role(value: str) -> str | None:
    """Recognize common EN/ES labels such as 'Pregunta (ES)' and 'Answer EN'."""
    normalized = unicodedata.normalize("NFKD", value.casefold())
    normalized = "".join(c for c in normalized if not unicodedata.combining(c))
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized).strip()
    if len(normalized) > 55:
        return None
    parts = normalized.split()
    if not parts:
        return None
    if parts[0] in {"question", "questions", "pregunta", "preguntas"}:
        return "question"
    if parts[0] in {"answer", "answers", "respuesta", "respuestas"}:
        return "answer"
    return None


def _clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:15_000]


def _header_language(value: str) -> Language | None:
    terms = set(normalize(value).split())
    es = bool(terms & {"es", "espanol", "spanish"})
    en = bool(terms & {"en", "ingles", "english"})
    if es and en:
        raise ValueError("XLSX Q&A headers must declare one language, not both EN and ES.")
    return "es" if es else "en" if en else None


def _xlsx_pairs(values: list[str]) -> list[tuple[int, int, Language | None]]:
    """Pair each question with one answer of the same declared language, in column order."""
    roles = [_header_role(value) for value in values]
    questions = [(i, _header_language(values[i])) for i, role in enumerate(roles) if role == "question"]
    answers = [(i, _header_language(values[i])) for i, role in enumerate(roles) if role == "answer"]
    pairs = []
    used: set[int] = set()
    for qi, language in questions:
        ai = next((i for i, answer_language in answers if i not in used and answer_language == language), None)
        if ai is not None:
            pairs.append((qi, ai, language))
            used.add(ai)
    if questions and answers and not pairs:
        raise ValueError("XLSX Question/Answer columns must have matching language labels (or both be unlabelled).")
    return pairs


def _check_zip(payload: bytes) -> None:
    """Prevent unusually compressed Office files from exhausting local resources."""
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            total = sum(item.file_size for item in archive.infolist())
            if total > MAX_ARCHIVE_UNCOMPRESSED_BYTES or len(archive.infolist()) > 10_000:
                raise ValueError("Office document is too large after decompression.")
    except zipfile.BadZipFile as exc:
        raise ValueError("Office document is not a valid ZIP container.") from exc


def _chunks(text: str, location: str, max_chars: int = 1250, overlap: int = 150) -> list[ParsedEntry]:
    text = text.strip()
    if not text:
        return []
    result: list[ParsedEntry] = []
    start = 0
    while start < len(text) and len(result) < MAX_ITEMS:
        end = min(start + max_chars, len(text))
        if end < len(text):
            whitespace = text.rfind(" ", max(start + max_chars // 2, start), end)
            if whitespace > start:
                end = whitespace
        segment = text[start:end].strip()
        if segment:
            result.append(ParsedEntry("text", "", "", segment, location))
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)
    return result


def _parse_text(payload: bytes, suffix: str) -> list[ParsedEntry]:
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("Text documents must use UTF-8 encoding.") from exc
    # Q:/A: blocks also work in Markdown files, without relying on a cloud LLM.
    qa = re.compile(r"(?im)^\s*(?:Q|Pregunta|Question)\s*:\s*(.+?)\s*\n\s*(?:A|Respuesta|Answer)\s*:\s*([\s\S]*?)(?=\n\s*(?:Q|Pregunta|Question)\s*:|\Z)")
    pairs = []
    for match in qa.finditer(text):
        pairs.append(ParsedEntry("qa", _clean(match.group(1)), _clean(match.group(2)), "", f"Línea {text[:match.start()].count(chr(10)) + 1}"))
    if pairs:
        return pairs[:MAX_ITEMS]
    return _chunks(text, "Documento de texto")


def _parse_xlsx(payload: bytes) -> list[ParsedEntry]:
    _check_zip(payload)
    workbook = load_workbook(io.BytesIO(payload), read_only=True, data_only=True)
    entries: list[ParsedEntry] = []
    try:
        for sheet in workbook.worksheets[:MAX_SHEETS]:
            header: list[tuple[int, int, Language | None]] | None = None
            for row_no, row in enumerate(sheet.iter_rows(values_only=True, max_col=30, max_row=MAX_ROWS_PER_SHEET), 1):
                values = [_clean(v) for v in row]
                if not any(values):
                    continue
                if header is None:
                    pairs = _xlsx_pairs(values)
                    if pairs:
                        header = pairs
                        continue
                if header is not None:
                    for qi, ai, language in header:
                        question = values[qi] if qi < len(values) else ""
                        answer = values[ai] if ai < len(values) else ""
                        if question and answer:
                            location = f"Hoja '{sheet.title}' · fila {row_no}"
                            if language is not None or len(header) > 1:
                                location += f" · columnas {get_column_letter(qi + 1)}/{get_column_letter(ai + 1)}"
                            if language is not None:
                                location += f" · {language.upper()}"
                            entries.append(ParsedEntry("qa", question, answer, "", location, language))
                            if len(entries) >= MAX_ITEMS:
                                break
                else:
                    entries.extend(_chunks(" | ".join(v for v in values if v), f"Hoja '{sheet.title}' · fila {row_no}"))
                if len(entries) >= MAX_ITEMS:
                    break
            if len(entries) >= MAX_ITEMS:
                break
    finally:
        workbook.close()
    return entries[:MAX_ITEMS]


def _parse_docx(payload: bytes) -> list[ParsedEntry]:
    _check_zip(payload)
    doc = Document(io.BytesIO(payload))
    entries: list[ParsedEntry] = []
    paragraphs = [_clean(p.text) for p in doc.paragraphs if p.text.strip()]
    entries.extend(_chunks("\n".join(paragraphs), "Párrafos"))
    for table_no, table in enumerate(doc.tables[:100], 1):
        qa_columns: tuple[int, int] | None = None
        if table.rows:
            roles = [_header_role(_clean(c.text)) for c in table.rows[0].cells]
            q = next((i for i, v in enumerate(roles) if v == "question"), None)
            a = next((i for i, v in enumerate(roles) if v == "answer"), None)
            if q is not None and a is not None and q != a:
                qa_columns = (q, a)
        for row_no, row in enumerate(table.rows[:MAX_ROWS_PER_SHEET], 1):
            cells = [_clean(c.text) for c in row.cells]
            if qa_columns:
                if row_no == 1:
                    continue
                qi, ai = qa_columns
                if len(cells) > max(qi, ai) and cells[qi] and cells[ai]:
                    entries.append(ParsedEntry("qa", cells[qi], cells[ai], "", f"Tabla {table_no} · fila {row_no}"))
            elif any(cells):
                entries.extend(_chunks(" | ".join(cells), f"Tabla {table_no} · fila {row_no}"))
            if len(entries) >= MAX_ITEMS:
                return entries[:MAX_ITEMS]
    return entries[:MAX_ITEMS]


def _parse_pdf(payload: bytes) -> list[ParsedEntry]:
    reader = PdfReader(io.BytesIO(payload), strict=False)
    if reader.is_encrypted:
        raise ValueError("Encrypted PDFs are not supported in this version.")
    if len(reader.pages) > MAX_PAGES:
        raise ValueError(f"PDF has more than {MAX_PAGES} pages.")
    entries = []
    for page_no, page in enumerate(reader.pages, 1):
        entries.extend(_chunks(page.extract_text() or "", f"Página {page_no}"))
    return entries[:MAX_ITEMS]


def parse_file(filename: str, payload: bytes) -> list[ParsedEntry]:
    suffix = Path(filename).suffix.casefold()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError("Unsupported format. Use PDF, DOCX, XLSX, TXT, or MD.")
    try:
        if suffix in (".md", ".txt"):
            result = _parse_text(payload, suffix)
        elif suffix == ".xlsx":
            result = _parse_xlsx(payload)
        elif suffix == ".docx":
            result = _parse_docx(payload)
        else:
            result = _parse_pdf(payload)
    except (ValueError, RuntimeError):
        raise
    except Exception as exc:
        raise ValueError(f"Could not read this {suffix} file.") from exc
    if not result:
        raise ValueError("No readable text found. Scanned PDFs require OCR (not yet supported).")
    return result
