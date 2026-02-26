from io import BytesIO
from PIL import Image, ImageDraw


def render_snapshot(title: str, mode: str, status: str, lines: list[str], tool_calls: int, team_version: str = 'n/a', marketplace_id: str = 'n/a') -> bytes:
    img = Image.new('RGB', (900, 560), color=(15, 15, 20))
    draw = ImageDraw.Draw(img)
    draw.text((20, 20), f'Agentora Snapshot: {title}', fill=(220, 220, 255))
    draw.text((20, 50), f'Mode: {mode} | Status: {status} | Tool calls: {tool_calls}', fill=(170, 170, 190))
    draw.text((20, 80), f'Team version: {team_version} | Marketplace: {marketplace_id}', fill=(170, 170, 190))
    y = 120
    for line in lines[-10:]:
        draw.text((20, y), line[:120], fill=(230, 230, 230))
        y += 38
    out = BytesIO()
    img.save(out, format='PNG')
    return out.getvalue()
