"""Build the repo's diagrams as phone-friendly SVG images.

Every diagram is drawn on a 400-unit-wide portrait canvas, so on a phone
(about 350 px of content width) it shows full width at ~0.9 scale with
no zooming and no sideways scrolling. Body text is 20 units and nothing is
smaller than 17. Each diagram is written twice: a light and a dark version,
which the Markdown files pick between with <picture>.

Each SVG is also exported as a PNG at 3x (1200 px wide). The Markdown uses the
PNGs: the GitHub mobile app renders neither Mermaid nor SVG reliably, but every
GitHub client shows a PNG.

Run:  python docs/img/make_diagrams.py   (needs Pillow to measure text and
      rsvg-convert, from librsvg, to export the PNGs)
"""
from __future__ import annotations

import shutil
import subprocess
from html import escape
from pathlib import Path

from PIL import ImageFont

OUT = Path(__file__).parent
W = 400          # canvas width
PAD = 14         # outer margin
FONT = "system-ui,-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
MONO = "ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"

# DejaVu is wider than the phone system fonts, so wrapping with it is conservative.
_DJ = "/usr/share/fonts/truetype/dejavu/"
_fonts: dict = {}


def tw(text: str, size: int, bold: bool = False, mono: bool = False) -> float:
    name = "DejaVuSansMono.ttf" if mono else ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")
    key = (name, size)
    if key not in _fonts:
        _fonts[key] = ImageFont.truetype(_DJ + name, size)
    return _fonts[key].getlength(text)


def wrap(text: str, width: float, size: int, bold=False, mono=False) -> list[str]:
    lines: list[str] = []
    for para in text.split("\n"):
        cur = ""
        for word in para.split(" "):
            trial = (cur + " " + word).strip()
            if tw(trial, size, bold, mono) <= width or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        lines.append(cur)
    return lines


THEMES = {
    "light": {
        "bg": "#FFFFFF", "ink": "#0F172A", "muted": "#475569", "line": "#64748B",
        "pill": "#F1F5F9",
        "input": ("#F1F5F9", "#475569"), "ai": ("#EDE9FE", "#6D28D9"),
        "code": ("#DCFCE7", "#15803D"), "out": ("#FEF3C7", "#B45309"),
        "person": ("#DBEAFE", "#1D4ED8"), "reject": ("#FEE2E2", "#B91C1C"),
        "db": ("#E0F2FE", "#0369A1"),
    },
    "dark": {
        "bg": "#0D1117", "ink": "#E6EDF3", "muted": "#9DA7B3", "line": "#8B949E",
        "pill": "#21262D",
        "input": ("#1F2630", "#8B949E"), "ai": ("#2A2045", "#B794F6"),
        "code": ("#12301F", "#4ADE80"), "out": ("#3A2A0E", "#FBBF24"),
        "person": ("#14274A", "#60A5FA"), "reject": ("#3B1416", "#F87171"),
        "db": ("#0C2A3D", "#38BDF8"),
    },
}
LEGEND = {"input": "Your files", "ai": "AI", "code": "Code", "out": "Output",
          "person": "Person", "reject": "Rejected", "db": "Storage"}


class Canvas:
    def __init__(self, theme: str):
        self.t = THEMES[theme]
        self.parts: list[str] = []
        self.y = PAD

    # -- primitives --------------------------------------------------------
    def text(self, x, y, s, size=20, bold=False, color=None, anchor="start", mono=False):
        fam = MONO if mono else FONT
        self.parts.append(
            f'<text x="{x:.1f}" y="{y:.1f}" font-family="{fam}" font-size="{size}" '
            f'font-weight="{700 if bold else 400}" fill="{color or self.t["ink"]}" '
            f'text-anchor="{anchor}">{escape(s)}</text>')

    def rect(self, x, y, w, h, fill, stroke, r=12, dash=False, sw=2):
        d = ' stroke-dasharray="7 5"' if dash else ""
        self.parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{r}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{d}/>')

    def arrow(self, x1, y1, x2, y2, label=None):
        c = self.t["line"]
        if abs(x1 - x2) < 1:
            path = f"M{x1:.1f},{y1:.1f} L{x2:.1f},{y2 - 9:.1f}"
        else:
            my = (y1 + y2) / 2
            path = f"M{x1:.1f},{y1:.1f} L{x1:.1f},{my:.1f} L{x2:.1f},{my:.1f} L{x2:.1f},{y2 - 9:.1f}"
        self.parts.append(f'<path d="{path}" fill="none" stroke="{c}" stroke-width="2.5"/>')
        self.parts.append(
            f'<path d="M{x2 - 7:.1f},{y2 - 11:.1f} L{x2 + 7:.1f},{y2 - 11:.1f} L{x2:.1f},{y2:.1f} Z" fill="{c}"/>')
        if label:
            lx = x2 if abs(x1 - x2) >= 1 else x1
            ly = (y1 + y2) / 2 + (0 if abs(x1 - x2) < 1 else 0)
            w = tw(label, 17, True) + 18
            self.rect(lx - w / 2, ly - 14, w, 28, self.t["bg"], c, r=14, sw=1.5)
            self.text(lx, ly + 6, label, 17, True, self.t["muted"], "middle")

    # -- composite pieces ----------------------------------------------------
    def node(self, x, w, s, kind, tag=None, size=20, y=None, decision=False, measure=False, force_h=None):
        """Rounded box with wrapped, centred text. Returns (height)."""
        fill, stroke = self.t[kind]
        inner = w - 28
        lines = wrap(s, inner, size, bold=decision)
        lh = size * 1.3
        top = 14 + (26 if tag else 0)
        h = top + lh * len(lines) + 10
        if measure:
            return h
        h = force_h or h
        y = self.y if y is None else y
        self.rect(x, y, w, h, fill, stroke, r=6 if decision else 12, dash=False, sw=2.5 if decision else 2)
        if decision:  # a small diamond badge marks a yes/no check
            cx, cy = x + w - 18, y + 18
            self.parts.append(
                f'<path d="M{cx},{cy - 9} L{cx + 9},{cy} L{cx},{cy + 9} L{cx - 9},{cy} Z" fill="{stroke}"/>')
        if tag:
            self.text(x + 14, y + 27, tag.upper(), 17, True, stroke)
        ty = y + top + size + (h - (top + lh * len(lines) + 10)) / 2
        for ln in lines:
            self.text(x + w / 2, ty, ln, size, decision, self.t["ink"], "middle")
            ty += lh
        return h

    def row(self, items, gap=12, x0=PAD, width=W - 2 * PAD):
        """items: list of dicts(text, kind, tag?, decision?). Draws side by side.
        Returns list of (cx, top, bottom)."""
        n = len(items)
        w = (width - gap * (n - 1)) / n
        hs = [self.node(0, w, it["text"], it["kind"], it.get("tag"), measure=True,
                        decision=it.get("decision", False)) for it in items]
        h = max(hs)
        out = []
        for i, it in enumerate(items):
            x = x0 + i * (w + gap)
            # every box in a row gets the row's tallest height, so the row reads as one band
            self.node(x, w, it["text"], it["kind"], it.get("tag"), y=self.y,
                      decision=it.get("decision", False), force_h=h)
            out.append((x + w / 2, self.y, self.y + h))
        self.y += h
        return out

    def title(self, s, sub=None):
        for ln in wrap(s, W - 2 * PAD, 24, True):
            self.y += 26
            self.text(PAD, self.y, ln, 24, True)
        if sub:
            for ln in wrap(sub, W - 2 * PAD, 18):
                self.y += 24
                self.text(PAD, self.y, ln, 18, False, self.t["muted"])
        self.y += 14

    def legend(self, kinds):
        x = PAD
        y = self.y
        for k in kinds:
            fill, stroke = self.t[k]
            label = LEGEND[k]
            w = tw(label, 17, True) + 36
            if x + w > W - PAD:
                x = PAD
                y += 36
            self.rect(x, y, w, 30, fill, stroke, r=15, sw=1.5)
            self.parts.append(f'<circle cx="{x + 15}" cy="{y + 15}" r="5" fill="{stroke}"/>')
            self.text(x + 26, y + 21, label, 17, True, self.t["ink"])
            x += w + 8
        self.y = y + 30 + 16

    def gap(self, h=40):
        self.y += h

    def svg(self, alt):
        h = self.y + PAD
        body = "\n".join(self.parts)
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {h:.0f}" '
                f'width="{W}" height="{h:.0f}" role="img" aria-label="{escape(alt)}">\n'
                f'<title>{escape(alt)}</title>\n'
                f'<rect width="{W}" height="{h:.0f}" rx="16" fill="{self.t["bg"]}"/>\n{body}\n</svg>\n')


def connect(c: Canvas, src, dst, labels=None, gap=None):
    """Arrows from every box in src row to every box in dst row (fan in / out)."""
    for i, (sx, _, sb) in enumerate(src):
        for j, (dx, dt, _) in enumerate(dst):
            if len(src) > 1 and len(dst) > 1 and i != j:
                continue
            lab = labels[j] if labels and len(dst) > 1 else (labels[0] if labels else None)
            c.arrow(sx, sb, dx, dt, lab if (i == 0 or len(dst) > 1) else None)


def flow(theme, alt, title, sub, legend, rows, labels=None, gap=46):
    """rows: list of item lists. labels: {row_index: [label per dst box]}"""
    c = Canvas(theme)
    c.title(title, sub)
    if legend:
        c.legend(legend)
    # two passes: draw rows, remember positions, then arrows on top of gaps
    pos = []
    for i, items in enumerate(rows):
        if i:
            c.gap(gap)
        pos.append(c.row(items))
    for i in range(1, len(rows)):
        connect(c, pos[i - 1], pos[i], (labels or {}).get(i))
    return c.svg(alt)


# ---------------------------------------------------------------------------
# The diagrams
# ---------------------------------------------------------------------------
def d_overview(t):
    return flow(t, "How Sightline works: your files, AI reads, code checks, AI explains, findings.",
                "How it works in 60 seconds", None, ["ai", "code"], [
                    [{"text": "Your files: contract + invoices", "kind": "input"}],
                    [{"text": "Reads the layout", "kind": "ai", "tag": "1 · AI"}],
                    [{"text": "Checks every line and computes every dollar", "kind": "code", "tag": "2 · Code"}],
                    [{"text": "Explains in plain English. Can't add numbers", "kind": "ai", "tag": "3 · AI"}],
                    [{"text": "Findings: $ amount · file + row · dispute note", "kind": "out"}],
                ], gap=40)


def d_read_check(t):
    return flow(t, "Step 1 and 2: AI reads both files, code verifies, then rejects or computes.",
                "Steps 1–2: read, then verify", "Nothing the AI reads is trusted until code confirms it.",
                ["ai", "code", "reject"], [
                    [{"text": "Contract (PDF)", "kind": "input"},
                     {"text": "Invoices (CSV · Excel · PDF)", "kind": "input"}],
                    [{"text": "Finds terms + page citations", "kind": "ai", "tag": "AI · small"},
                     {"text": "Maps columns + stated totals", "kind": "ai", "tag": "AI · small"}],
                    [{"text": "Types, row counts and totals reconcile? Citations on the page?",
                      "kind": "code", "tag": "Code check", "decision": True}],
                    [{"text": "Rejected + logged", "kind": "reject"},
                     {"text": "Rules compute every dollar, to the cent", "kind": "code"}],
                ], labels={3: ["no", "yes"]})


def d_explain(t):
    return flow(t, "Step 3: AI explains code's numbers; a number guard swaps in a template if AI adds a figure.",
                "Step 3: explain, with a number guard", "The AI may only use figures the code produced.",
                ["ai", "code", "out"], [
                    [{"text": "Dollar amounts from code", "kind": "code"}],
                    [{"text": "Writes explanation + dispute note", "kind": "ai", "tag": "AI · large"}],
                    [{"text": "Any figure the code didn't produce?", "kind": "code",
                      "tag": "Number guard", "decision": True}],
                    [{"text": "Use code's template", "kind": "code"},
                     {"text": "Keep the AI text", "kind": "ai"}],
                    [{"text": "Findings: amount · file + row or page · dispute note", "kind": "out"}],
                    [{"text": "DuckDB locally · BigQuery in production", "kind": "db"}],
                ], labels={3: ["yes", "no"]}, gap=42)


def d_architecture(t):
    c = Canvas(t)
    c.title("Architecture", "One engine core. Domain knowledge lives in a corpus plugin.")
    c.legend(["ai", "code", "db"])
    ways = c.row([{"text": "CLI", "kind": "input"}, {"text": "API", "kind": "input"},
                  {"text": "Web page", "kind": "input"}], gap=10)
    steps = [
        {"text": "Ingest: CSV · Excel · PDF → tables", "kind": "code"},
        {"text": "Mapping: AI proposes, code validates", "kind": "code", "tag": "+ AI · small model"},
        {"text": "Corpus plugin: parse contract, run rules", "kind": "code"},
        {"text": "Explainer with number guard", "kind": "code", "tag": "+ AI · large model"},
        {"text": "DuckDB now · BigQuery later", "kind": "db"},
    ]
    prev = ways
    for s in steps:
        c.gap(40)
        cur = c.row([s])
        connect(c, prev, cur)
        prev = cur
    c.gap(18)
    note = "AI calls go through the model router: Claude · Gemini · offline mock"
    for ln in wrap(note, W - 2 * PAD, 18):
        c.y += 24
        c.text(PAD, c.y, ln, 18, False, c.t["muted"])
    return c.svg("Architecture: CLI, API or web page feed ingest, mapping, corpus plugin, "
                 "explainer, then DuckDB or BigQuery.")


def branch_list(t, alt, title, sub, head, items, note=None, legend=None):
    """A question box, then a vertical trunk with one labelled branch per outcome."""
    c = Canvas(t)
    c.title(title, sub)
    if legend:
        c.legend(legend)
    if head:
        top = c.row([head])
        trunk_x = PAD + 22
        c.parts.append(f'<path d="M{trunk_x},{top[0][2]} L{trunk_x},{top[0][2] + 20}" '
                       f'stroke="{c.t["line"]}" stroke-width="2.5"/>')
        c.gap(20)
        y_start = c.y
    else:
        trunk_x = PAD + 22
        y_start = c.y
    bx = PAD + 46
    bw = W - PAD - bx
    mids = []
    for label, text, kind in items:
        c.gap(10)
        fill, stroke = c.t[kind]
        lines = wrap(text, bw - 24, 19)
        lh = 24
        h = 54 + lh * len(lines)
        y = c.y
        c.rect(bx, y, bw, h, fill, stroke)
        c.text(bx + 12, y + 26, label, 18, True, stroke)
        ty = y + 26 + 26
        for ln in lines:
            c.text(bx + 14, ty, ln, 19)
            ty += lh
        mids.append(y + 25)
        c.y += h
    line = c.t["line"]
    c.parts.append(f'<path d="M{trunk_x},{y_start} L{trunk_x},{mids[-1]}" stroke="{line}" stroke-width="2.5"/>')
    for m in mids:
        c.parts.append(f'<path d="M{trunk_x},{m} L{bx - 9},{m}" stroke="{line}" stroke-width="2.5"/>')
        c.parts.append(f'<path d="M{bx - 11},{m - 7} L{bx - 11},{m + 7} L{bx},{m} Z" fill="{line}"/>')
    if note:
        c.gap(10)
        for ln in wrap(note, W - 2 * PAD, 18):
            c.y += 24
            c.text(PAD, c.y, ln, 18, False, c.t["muted"])
    return c.svg(alt)


def d_runbook(t):
    return branch_list(
        t, "Troubleshooting: find the message the audit printed, apply the matching fix.",
        "Audit failed or looks wrong?", "Match the message it printed to its fix.",
        None, [
            ("file rejected: unknown headers", "Add an AI key, or add header synonyms to the corpus schema", "reject"),
            ("file rejected: totals off", "The input is wrong. Fix the file; never loosen the check", "reject"),
            ("No rate agreement found", "Put the contract_marker phrase on page 1 of the contract PDF", "reject"),
            ("terms failed verification", "The named term is missing, out of range, or not on its cited page", "reject"),
            ("cost n/a", "Set SIGHTLINE_PRICE_<MODEL> in your .env file", "input"),
            ("llm text rejected", "Expected: the AI wrote a number code didn't make, so the template was used", "code"),
        ], note="Rejected files are listed in runs/rejected_mappings.jsonl")


def d_problem(t):
    c = Canvas(t)
    c.title("The problem shape", "A governing document, and documents that should follow it.")
    top = c.row([{"text": "Governing doc: contract · PPM · MSA", "kind": "input", "tag": "Rules"},
                 {"text": "Invoices · pro forma · statements", "kind": "input", "tag": "Should follow"}])
    c.gap(44)
    q = c.row([{"text": "Do the numbers agree?", "kind": "code", "decision": True}])
    connect(c, top, q)
    # outcomes as a branch list under the question
    trunk_x = W / 2
    items = [("no, provably", "verifiable finding, with its dollar amount", "out"),
             ("unclear", "judgment_required: a person decides", "person"),
             ("yes", "clean, nothing to report", "code")]
    c.gap(30)
    for label, text, kind in items:
        h = c.node(PAD + 30, W - 2 * PAD - 30, text, kind, tag=label, measure=True)
        c.node(PAD + 30, W - 2 * PAD - 30, text, kind, tag=label)
        mid = c.y + 25
        c.parts.append(f'<path d="M{PAD + 10},{mid} L{PAD + 21},{mid}" stroke="{c.t["line"]}" stroke-width="2.5"/>')
        c.parts.append(f'<path d="M{PAD + 19},{mid - 7} L{PAD + 19},{mid + 7} L{PAD + 30},{mid} Z" fill="{c.t["line"]}"/>')
        last = mid
        c.y += h + 14
    c.y -= 14
    qb = q[0][2]
    line = c.t["line"]
    c.parts.append(f'<path d="M{trunk_x},{qb} L{trunk_x},{qb + 15} L{PAD + 10},{qb + 15} L{PAD + 10},{last}" '
                   f'fill="none" stroke="{line}" stroke-width="2.5"/>')
    return c.svg("Governing document and follow-on documents are compared; outcomes are "
                        "verifiable finding, judgment_required, or clean.")


def d_agents(t):
    c = Canvas(t)
    c.title("CRE agent map", "One orchestrator routes each question to a specialist.")
    c.legend(["ai", "out", "person"])
    q = c.row([{"text": "User question", "kind": "input"}])
    c.gap(40)
    o = c.row([{"text": "Orchestrator", "kind": "ai"}])
    connect(c, q, o)
    c.gap(40)
    # group frame for the four agents
    gy = c.y
    c.y += 40
    c.row([{"text": "Extractor: deal sheet + citations", "kind": "ai"},
                {"text": "Investor Q&A", "kind": "ai"}], x0=PAD + 12, width=W - 2 * PAD - 24)
    c.gap(12)
    r2 = c.row([{"text": "Summarizer: memos", "kind": "ai"},
                {"text": "Risk agent: cross-checks", "kind": "ai"}], x0=PAD + 12, width=W - 2 * PAD - 24)
    c.y += 12
    frame = (f'<rect x="{PAD}" y="{gy}" width="{W - 2 * PAD}" height="{c.y - gy}" rx="14" fill="none" '
             f'stroke="{c.t["line"]}" stroke-width="2" stroke-dasharray="7 5"/>')
    c.parts.append(frame)
    c.text(PAD + 14, gy + 27, "ROUTES TO ONE OF", 17, True, c.t["muted"])
    c.arrow(o[0][0], o[0][2], o[0][0], gy)
    c.gap(42)
    v = c.row([{"text": "Provable from the documents?", "kind": "code", "decision": True}])
    c.arrow(r2[1][0], r2[1][2] + 12, r2[1][0], v[0][1])
    c.gap(46)
    res = c.row([{"text": "verifiable finding + citation", "kind": "out"},
                 {"text": "judgment_required: a person decides", "kind": "person"}])
    connect(c, v, res, ["yes", "no"])
    return c.svg("Agent map: user question to orchestrator, which routes to extractor, investor Q&A, "
                 "summarizer or risk agent; risk checks end as verifiable or judgment_required.")


def d_glossary(t):
    groups = [
        ("Real estate", "out", ["CRE", "PPM / OM", "NOI", "Cap rate", "Rent roll"]),
        ("Shipping", "input", ["DIM weight", "Zone", "Fuel surcharge", "Accessorial", "GRI"]),
        ("Software and data", "code", ["API", "CI", "DuckDB / BigQuery", "React / Vite"]),
        ("AI", "ai", ["LLM", "Token", "MCP", "Eval"]),
        ("This project", "person", ["verifiable", "judgment_required", "Corpus / plugin", "Number guard"]),
    ]
    c = Canvas(t)
    c.title("Sightline terms", "Five groups. Each term is defined in the table below.")
    for name, kind, terms in groups:
        fill, stroke = c.t[kind]
        # lay chips out first to know the card height
        x, y, rows = PAD + 14, 0, 1
        chips = []
        for term in terms:
            w = tw(term, 18, False, mono=term.islower() and "_" in term) + 24
            if x + w > W - PAD - 14:
                x, y, rows = PAD + 14, y + 42, rows + 1
            chips.append((x, y, w, term))
            x += w + 8
        h = 48 + rows * 42 + 6
        top = c.y
        c.rect(PAD, top, W - 2 * PAD, h, fill, stroke)
        c.text(PAD + 14, top + 31, name, 20, True, stroke)
        for x, y, w, term in chips:
            c.rect(x, top + 44 + y, w, 34, c.t["bg"], stroke, r=17, sw=1.5)
            c.text(x + w / 2, top + 44 + y + 23, term, 18, False, c.t["ink"], "middle")
        c.y += h + 12
    c.y -= 12
    return c.svg("Glossary map: real estate, shipping, software and data, AI, and project terms.")


def d_overbilling(t):
    data = [("Duplicate billing", 26.11), ("Wrong fuel %", 23.40), ("Missed discount", 22.43),
            ("Address correction billed twice", 18.00), ("Line total arithmetic", 10.00),
            ("Residential fee", 4.85), ("Billed weight", 3.99), ("Wrong zone", 3.64)]
    c = Canvas(t)
    c.title("Overbilling found, by type", "USD · synthetic invoices · total $112.42")
    fill, stroke = c.t["out"]
    mx = max(v for _, v in data)
    full = W - 2 * PAD
    for label, v in data:
        c.y += 22
        c.text(PAD, c.y, label, 19)
        c.text(W - PAD, c.y, f"${v:.2f}", 19, True, c.t["ink"], "end")
        c.y += 8
        c.rect(PAD, c.y, full, 18, c.t["pill"], c.t["pill"], r=9, sw=0)
        c.rect(PAD, c.y, max(full * v / mx, 18), 18, stroke, stroke, r=9, sw=0)
        c.y += 18 + 14
    c.y -= 6
    return c.svg("Overbilling by type: duplicate billing $26.11, wrong fuel % $23.40, missed discount "
                 "$22.43, address correction billed twice $18.00, line total arithmetic $10.00, "
                 "residential fee $4.85, billed weight $3.99, wrong zone $3.64.")


DIAGRAMS = {
    "overview": d_overview, "read-check": d_read_check, "explain": d_explain,
    "overbilling": d_overbilling, "glossary": d_glossary, "architecture": d_architecture,
    "runbook": d_runbook, "agents": d_agents, "problem": d_problem,
}

if __name__ == "__main__":
    for name, fn in DIAGRAMS.items():
        for theme in THEMES:
            svg = OUT / f"{name}-{theme}.svg"
            svg.write_text(fn(theme), encoding="utf-8")
            if shutil.which("rsvg-convert"):
                subprocess.run(["rsvg-convert", "-w", "1200", str(svg), "-o",
                                str(svg.with_suffix(".png"))], check=True)
                if shutil.which("convert"):  # ImageMagick: 128-colour PNG, ~70% smaller
                    png = str(svg.with_suffix(".png"))
                    subprocess.run(["convert", png, "-strip", "-dither", "None",
                                    "-colors", "128", "PNG8:" + png], check=True)
    print(f"wrote {len(DIAGRAMS) * len(THEMES)} diagrams to {OUT}")
