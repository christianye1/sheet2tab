"""Run the backend pipeline locally, without the server or the phone.

    python scripts/convert_file.py samples/ode_to_joy.musicxml
    python scripts/convert_file.py path/to/photo.jpg      # runs OMR first
    python scripts/convert_file.py FILE --json            # full JSON response
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.pipeline import musicxml_to_tab  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("file", help="MusicXML (.musicxml/.xml/.mxl) or image (.jpg/.png)")
    ap.add_argument("--json", action="store_true", help="print the full JSON result")
    args = ap.parse_args()

    path = Path(args.file)
    if path.suffix.lower() in {".jpg", ".jpeg", ".png"}:
        from app.pipeline import image_to_tab
        result = image_to_tab(path.read_bytes())
    else:
        result = musicxml_to_tab(path)

    if args.json:
        print(json.dumps(result, indent=2))
        return
    print(result["tab_text"])
    print(f"{len(result['notes'])} notes")
    for w in result["warnings"]:
        print(f"warning: {w}")


if __name__ == "__main__":
    main()
