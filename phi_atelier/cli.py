"""Run: python -m phi_atelier.cli --concept 'A city inside a dream'"""
from __future__ import annotations
import argparse
import json
from .core import ArtBrief, compile_brief


def main() -> None:
    parser = argparse.ArgumentParser(description="PhiAtelier prompt designer (no rendering or model call)")
    parser.add_argument("--concept", required=True)
    parser.add_argument("--symbolism", default="")
    parser.add_argument("--orientation", choices=["landscape", "portrait", "square"], default="landscape")
    parser.add_argument("--rendering", choices=["photoreal", "fine-art", "concept-art"], default="photoreal")
    parser.add_argument("--escher", type=int, default=1)
    parser.add_argument("--dali", type=int, default=1)
    parser.add_argument("--picasso", type=int, default=1)
    parser.add_argument("--restrictions", default="")
    args = parser.parse_args()
    payload = compile_brief(ArtBrief(
        concept=args.concept, symbolism=args.symbolism, orientation=args.orientation,
        rendering=args.rendering,
        influences={"escher": args.escher, "dali": args.dali, "picasso": args.picasso},
        restrictions=args.restrictions,
    ))
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
