"""Embed genuine live Mininet measurements in the standalone dashboard."""

import json
import os


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def save_live_payload(marker_name, payload, filename):
    result_path = os.path.join(PROJECT_ROOT, "results", filename)
    with open(result_path, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2)

    dashboard_path = os.path.join(PROJECT_ROOT, "index.html")
    with open(dashboard_path, encoding="utf-8") as stream:
        html = stream.read()
    begin, end = f"/*__{marker_name}_BEGIN__*/", f"/*__{marker_name}_END__*/"
    if begin not in html or end not in html:
        raise RuntimeError(f"Dashboard marker pair for {marker_name} is missing")
    start = html.index(begin) + len(begin)
    finish = html.index(end, start)
    html = html[:start] + " " + json.dumps(payload, separators=(",", ":")) + " " + html[finish:]
    with open(dashboard_path, "w", encoding="utf-8", newline="") as stream:
        stream.write(html)
    return result_path
