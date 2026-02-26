from pathlib import Path
import zipfile

root = Path(__file__).resolve().parents[1]
out = root / 'dist'
out.mkdir(exist_ok=True)
zip_path = out / 'agentora-v0.1-github-ready.zip'
exclude = {'dist', 'server/data', '.git', 'web/node_modules', 'web/dist', '__pycache__'}
with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
    for p in root.rglob('*'):
        rp = p.relative_to(root)
        if any(str(rp).startswith(e) for e in exclude):
            continue
        if p.is_file() and p.suffix not in {'.db', '.zip', '.png'}:
            zf.write(p, rp)
print(zip_path)
