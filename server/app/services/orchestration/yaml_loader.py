import yaml


def parse_team_yaml(yaml_text: str) -> dict:
    data = yaml.safe_load(yaml_text)
    required = {'name', 'mode', 'agents'}
    missing = required - set(data.keys())
    if missing:
        raise ValueError(f'missing keys: {sorted(missing)}')
    return data
