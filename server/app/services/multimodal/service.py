import hashlib
from pathlib import Path
from pypdf import PdfReader


def store_upload(run_id: int, filename: str, data: bytes) -> tuple[str, str]:
    d = Path('server/data/uploads') / f'run_{run_id}'
    d.mkdir(parents=True, exist_ok=True)
    p = d / filename
    p.write_bytes(data)
    return str(p), hashlib.sha256(data).hexdigest()


def extract_pdf_text(path: str) -> str:
    try:
        reader = PdfReader(path)
        return '\n'.join([page.extract_text() or '' for page in reader.pages]).strip()[:20000]
    except Exception:
        return ''


def model_can_vision(name: str) -> bool:
    low = name.lower()
    return any(k in low for k in ['llava', 'moondream', 'vision'])
