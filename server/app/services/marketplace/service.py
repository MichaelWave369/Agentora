import shutil
from pathlib import Path
import yaml


def semver_tuple(v: str) -> tuple:
    return tuple(int(x) for x in v.split('.'))


def list_marketplace_templates() -> list[dict]:
    rows = []
    for p in sorted(Path('agents/marketplace').glob('*.yaml')):
        data = yaml.safe_load(p.read_text(encoding='utf-8'))
        data['_path'] = str(p)
        rows.append(data)
    return rows


def install_template(name: str, version: str) -> Path:
    src = Path('agents/marketplace') / f'{name.lower()}.yaml'
    if not src.exists():
        raise FileNotFoundError(name)
    out = Path('server/data/user_templates')
    out.mkdir(parents=True, exist_ok=True)
    dest = out / f'{name}@{version}.yaml'
    shutil.copy2(src, dest)
    return dest
