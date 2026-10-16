"""Stage-oriented command line for local and container execution."""

import argparse


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    download = commands.add_parser("fetch", help="Download and verify one dataset manifest entry")
    download.add_argument("name")
    download.add_argument("--manifest", default="datasets/sources.json")
    download.add_argument("--cache", default="work/data")
    generate = commands.add_parser("generate", help="Generate image and geometry variants")
    generate.add_argument("--output", required=True)
    generate.add_argument("--source", help="Optional downloaded 3D anatomical NIfTI")
    evaluate = commands.add_parser("evaluate", help="Compare the installed brainhops with native expectations")
    evaluate.add_argument("--fixtures", required=True)
    evaluate.add_argument("--output", required=True)
    evaluate.add_argument("--brainhops-ref", default="installed")
    evaluate.add_argument("--brainhops-sha", default="unknown")
    evaluate.add_argument("--interface", choices=["python", "cli"], default="python")
    args = vars(parser.parse_args())
    command = args.pop("command")
    if command == "fetch":
        from .datasets import fetch
        print(fetch(args["manifest"], args["name"], args["cache"]))
    elif command == "generate":
        from .fixtures import generate
        generate(**args)
    else:
        from .evaluate import evaluate
        return 0 if evaluate(**args) else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

