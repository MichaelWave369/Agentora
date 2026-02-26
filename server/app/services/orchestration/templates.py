from pathlib import Path
import yaml


def load_templates() -> list[dict]:
    out = []
    for p in sorted(Path('teams').glob('*.yaml')):
        out.append(yaml.safe_load(p.read_text(encoding='utf-8')))
    return out
