#!/usr/bin/env python3
"""Generate docs/architecture.drawio - the project's architecture as a
multi-page draw.io file.

    .venv/bin/python scripts/make_architecture_diagram.py
    .venv/bin/python scripts/make_architecture_diagram.py --out /tmp/a.drawio

WHY A GENERATOR RATHER THAN A HAND-DRAWN FILE

A diagram drawn once is accurate once. Every box here carries a model id, a
port, a count or a capability, and all of those move. Generating the file from
constants that sit next to the claim they make means a wrong number is a one
line fix and a re-run, not an afternoon of dragging rectangles.

THE COLOUR SCHEME CARRIES THE ARGUMENT

Green is NVIDIA. Everything else is plain. That is the whole legend, and it is
deliberate: the question this diagram has to answer at a glance is which parts
of the system are NVIDIA's and which are not. Solid green is NVIDIA
infrastructure and the served models; a green outline is an NVIDIA framework or
library; a dashed green outline is present but not integrated. Plain grey boxes
are this project's own code, the UI, and the datastores.

Boxes name COMPONENTS, not files. A reader of an architecture diagram wants to
know what a thing is, not which module it lives in; the file paths are in
README.md and ENGINEERING.md where they belong.

The counts marked VERIFIED were read off the running box on 2026-10-05:
10 tools, 27 HTTP routes, 13 application metric series plus 19 DCGM GPU series,
and the table row counts.

The output is uncompressed draw.io XML, so it is diffable and opens in
app.diagrams.net, the desktop app, or the VS Code extension.
"""
from __future__ import annotations

import argparse
import os
import re
from xml.sax.saxutils import escape as _xesc

# --------------------------------------------------------------------------
# palette, taken from the use-case slides: a near-black green for section
# bands, NVIDIA green for anything NVIDIA, and plain paper for the rest.
# --------------------------------------------------------------------------
NVGRN = "#76B900"        # NVIDIA green - every NVIDIA border
NVSOLID = "#5B8C3A"      # filled green - served models and NVIDIA infrastructure
BAND = "#14302A"         # section bands, near-black green
LANE = "#1E4035"         # lane headers, a shade up from the bands
PAPER = "#FCFCFA"        # ordinary components
EDGE = "#AEB7AC"         # their border
ACCENT_G = "#5B8C3A"     # objective rule
ACCENT_O = "#C1562A"     # outcome rule

_BOX = ("rounded=0;whiteSpace=wrap;html=1;align=left;verticalAlign=top;"
        "spacing=4;spacingLeft=8;spacingTop=2;fontSize=11;")

# NVIDIA framework / library: white, green outline.
S_NV = _BOX + f"fillColor=#FFFFFF;strokeColor={NVGRN};strokeWidth=2;fontColor=#17301A;"
# NVIDIA served model or infrastructure: filled green.
S_NVB = _BOX + f"fillColor={NVSOLID};strokeColor=#446B29;strokeWidth=2;fontColor=#FFFFFF;"
# Not NVIDIA: this project's code, the UI, the datastores.
S_STD = _BOX + f"fillColor={PAPER};strokeColor={EDGE};strokeWidth=1;fontColor=#1C2B25;"
# Present but not integrated.
S_ROAD = (_BOX + f"fillColor=#FFFFFF;strokeColor={NVGRN};strokeWidth=2;"
          "dashed=1;dashPattern=6 4;fontColor=#4A7023;")

S_LANE = ("rounded=0;whiteSpace=wrap;html=1;align=left;verticalAlign=middle;"
          f"spacingLeft=10;fontSize=11;fontStyle=1;fillColor={LANE};"
          "strokeColor=none;fontColor=#FFFFFF;")
S_BAND = ("rounded=0;whiteSpace=wrap;html=1;align=center;verticalAlign=middle;"
          f"fontSize=12;fontStyle=1;fillColor={BAND};"
          "strokeColor=none;fontColor=#FFFFFF;")
S_BANDL = S_BAND.replace("align=center", "align=left") + "spacingLeft=12;"
S_GROUP = ("rounded=0;whiteSpace=wrap;html=1;align=left;verticalAlign=top;"
           "spacingLeft=10;spacingTop=4;fontSize=11;fontStyle=1;"
           f"fillColor=#F7F8F5;strokeColor={EDGE};fontColor={BAND};")
S_TITLE = ("rounded=0;whiteSpace=wrap;html=1;align=left;verticalAlign=middle;"
           "spacingLeft=14;fontSize=20;fontStyle=1;fillColor=none;"
           "strokeColor=none;fontColor=#101814;")
S_NOTE = ("rounded=0;whiteSpace=wrap;html=1;align=left;verticalAlign=top;"
          f"spacing=6;fontSize=11;fillColor=#FFFFFF;strokeColor={EDGE};"
          "fontColor=#33403A;")
S_PANEL_L = ("rounded=0;whiteSpace=wrap;html=1;align=left;verticalAlign=top;"
             "spacing=8;spacingLeft=14;fontSize=11;fillColor=#EFF3EA;"
             "strokeColor=none;fontColor=#1D2E1B;")
S_PANEL_R = ("rounded=0;whiteSpace=wrap;html=1;align=left;verticalAlign=top;"
             "spacing=8;spacingLeft=14;fontSize=11;fillColor=#FAEADF;"
             "strokeColor=none;fontColor=#3A2114;")
S_RULE_G = f"rounded=0;html=1;fillColor={ACCENT_G};strokeColor=none;"
S_RULE_O = f"rounded=0;html=1;fillColor={ACCENT_O};strokeColor=none;"
S_CHIP = ("rounded=0;whiteSpace=wrap;html=1;align=center;verticalAlign=middle;"
          f"fontSize=10;fontStyle=1;fillColor={NVSOLID};strokeColor=none;"
          "fontColor=#FFFFFF;")
S_CHIP_R = ("rounded=0;whiteSpace=wrap;html=1;align=center;verticalAlign=middle;"
            f"fontSize=10;fontStyle=1;fillColor=#FFFFFF;strokeColor={NVGRN};"
            "dashed=1;dashPattern=6 4;fontColor=#4A7023;")

S_START = ("ellipse;whiteSpace=wrap;html=1;align=center;verticalAlign=middle;"
           f"fontSize=11;fontStyle=1;fillColor=#FFFFFF;strokeColor={BAND};"
           "strokeWidth=2;fontColor=#14302A;")
S_END = ("ellipse;whiteSpace=wrap;html=1;align=center;verticalAlign=middle;"
         f"fontSize=11;fontStyle=1;fillColor={NVSOLID};strokeColor=#446B29;"
         "strokeWidth=2;fontColor=#FFFFFF;")
S_DEC = ("rhombus;whiteSpace=wrap;html=1;align=center;verticalAlign=middle;"
         f"fontSize=10;fillColor=#FFFFFF;strokeColor={BAND};strokeWidth=2;"
         "fontColor=#14302A;")

E_MAIN = ("edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;jettySize=auto;"
          f"strokeColor={BAND};strokeWidth=1.6;endArrow=block;endFill=1;"
          "fontSize=10;fontColor=#33403A;labelBackgroundColor=#FFFFFF;")
E_SIDE = ("edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;jettySize=auto;"
          f"strokeColor={ACCENT_O};strokeWidth=1.4;endArrow=block;endFill=1;"
          "dashed=1;fontSize=10;fontColor=#9E441F;"
          "labelBackgroundColor=#FFFFFF;")
E_FEED = ("edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;jettySize=auto;"
          f"strokeColor={NVSOLID};strokeWidth=1.4;endArrow=block;endFill=1;"
          "dashed=1;fontSize=10;fontColor=#446B29;"
          "labelBackgroundColor=#FFFFFF;")


def esc(s: str) -> str:
    return _xesc(s, {'"': "&quot;"})


# Fills dark enough that a grey sub-line disappears on them.
_DARK_FILLS = (NVSOLID, BAND, LANE)


def lbl(title: str, sub: str = "", style: str = "") -> str:
    """A bold name over a small muted line. The sub line carries the evidence -
    a model id, a port, a capability - so no box is a noun with nothing behind
    it. On a filled-green or banded box the muted grey is invisible, so the
    sub-line goes pale instead; the colour follows the fill rather than being
    passed in at every call site."""
    title = title.replace("\n", "<br>")
    out = f"<b>{title}</b>"
    if sub:
        sub = sub.replace("\n", "<br>")
        on_dark = any(f"fillColor={c}" in style for c in _DARK_FILLS)
        colour = "#DCE8CF" if on_dark else "#5C6B64"
        out += f'<br><font style="font-size:9.5px;color:{colour};">{sub}</font>'
    return out


class Page:
    """One draw.io tab. Ids are page-scoped so pages can be reordered or
    dropped without renumbering anything."""

    def __init__(self, name: str, slug: str, width: int, height: int):
        self.name = name
        self.slug = slug
        self.width = width
        self.height = height
        self.cells: list[str] = []
        self._n = 0

    def _id(self) -> str:
        self._n += 1
        return f"{self.slug}-{self._n}"

    def box(self, x, y, w, h, style, title, sub="", _id=None) -> str:
        cid = _id or self._id()
        self.cells.append(
            f'        <mxCell id="{cid}" value="{esc(lbl(title, sub, style))}" '
            f'style="{esc(style)}" vertex="1" parent="1">\n'
            f'          <mxGeometry x="{x}" y="{y}" width="{w}" '
            f'height="{h}" as="geometry"/>\n        </mxCell>')
        return cid

    def raw(self, x, y, w, h, style, html) -> str:
        cid = self._id()
        self.cells.append(
            f'        <mxCell id="{cid}" value="{esc(html)}" '
            f'style="{esc(style)}" vertex="1" parent="1">\n'
            f'          <mxGeometry x="{x}" y="{y}" width="{w}" '
            f'height="{h}" as="geometry"/>\n        </mxCell>')
        return cid

    def edge(self, src, dst, style=E_MAIN, label="", exits=None) -> str:
        cid = self._id()
        st = style + (exits or "")
        self.cells.append(
            f'        <mxCell id="{cid}" value="{esc(label)}" '
            f'style="{esc(st)}" edge="1" parent="1" '
            f'source="{src}" target="{dst}">\n'
            f'          <mxGeometry relative="1" as="geometry"/>\n'
            f'        </mxCell>')
        return cid

    def render(self) -> str:
        body = "\n".join(self.cells)
        return (
            f'  <diagram id="{self.slug}" name="{esc(self.name)}">\n'
            f'    <mxGraphModel dx="1422" dy="800" grid="0" gridSize="10" '
            f'guides="1" tooltips="1" connect="1" arrows="1" fold="1" '
            f'page="1" pageScale="1" pageWidth="{self.width}" '
            f'pageHeight="{self.height}" math="0" shadow="0">\n'
            f'      <root>\n'
            f'        <mxCell id="{self.slug}-r0"/>\n'
            f'        <mxCell id="1" parent="{self.slug}-r0"/>\n'
            f'{body}\n'
            f'      </root>\n'
            f'    </mxGraphModel>\n'
            f'  </diagram>')


def spread(x: int, w: int, n: int, pad: int = 10, gap: int = 10) -> list[tuple[int, int]]:
    """n equal boxes across a lane. Returns (x, width) pairs."""
    bw = (w - 2 * pad - (n - 1) * gap) // n
    return [(x + pad + i * (bw + gap), bw) for i in range(n)]


def row(page: Page, x: int, y: int, w: int, h: int, items, pad=10, gap=10):
    """A lane's worth of boxes. items = [(style, title, sub), ...]"""
    out = []
    for (bx, bw), (style, title, sub) in zip(spread(x, w, len(items), pad, gap),
                                             items):
        out.append(page.box(bx, y, bw, h, style, title, sub))
    return out


# ==========================================================================
# PAGE 1 - the system map
# ==========================================================================
def page_architecture() -> Page:
    p = Page("1 · Architecture", "arch", 1700, 1270)

    p.raw(40, 12, 1000, 38, S_TITLE, "<b>AGENTIC AI USE CASE</b>")
    p.raw(40, 52, 1200, 30,
          S_TITLE.replace("fontSize=20", "fontSize=15")
                 .replace("fontColor=#101814", "fontColor=#3A4A42"),
          "Automotive Service Operations Intelligence Agent")

    # ------------------------------------------------- objective / outcome
    p.raw(40, 84, 5, 118, S_RULE_G, "")
    p.raw(45, 84, 795, 118, S_PANEL_L,
          '<b style="font-size:12px;">OBJECTIVE</b><br>'
          '<font style="font-size:11px;">A service department\'s true state '
          'lives in what technicians say during the shift, and it is lost. '
          'Spoken updates never reach the DMS, the advisor re-walks the shop '
          'to answer &quot;is this car safe to release?&quot;, and the '
          'handover is rebuilt from memory. Status is stale, blocked vehicles '
          'sit unnoticed, and nobody can show how a figure was arrived '
          'at.</font>')

    p.raw(860, 84, 5, 118, S_RULE_O, "")
    p.raw(865, 84, 795, 118, S_PANEL_R,
          '<b style="font-size:12px;">BUSINESS OUTCOME</b><br>'
          '<font style="font-size:11px;">'
          '• Capture the shift by speaking, not by typing into a DMS<br>'
          '• Surface blocked and at-risk vehicles the moment they block<br>'
          '• Hand over a shift in one prioritised, cited page<br>'
          '• Every figure computed and traceable to an update id<br>'
          '• Runs on one L40S — no customer data leaves the box</font>')

    # ------------------------------------------------------- chips + label
    p.raw(40, 214, 300, 30,
          S_TITLE.replace("fontSize=20", "fontSize=14").replace("spacingLeft=14", "spacingLeft=0"),
          "<b>ARCHITECTURE</b>")
    p.box(1118, 216, 180, 26, S_CHIP, "NVIDIA · SERVED")
    p.box(1304, 216, 180, 26, S_NV + "align=center;verticalAlign=middle;"
          "fontStyle=1;fontSize=10;spacingLeft=0;", "NVIDIA · FRAMEWORK")
    p.box(1490, 216, 170, 26, S_CHIP_R, "NOT INTEGRATED")

    Y0 = 252
    LX, LW = 40, 240
    CX, CW = 324, 1000
    RX, RW = 1368, 292

    p.box(CX, Y0, CW, 26, S_BAND,
          "SERVICE OPERATIONS INTELLIGENCE PLATFORM")

    # ---------------------------------------------------------------- left
    p.box(LX, Y0, LW, 26, S_BANDL, "Shop Floor Inputs")
    g = Y0 + 30
    p.box(LX, g, LW, 56, S_STD, "Spoken update",
          "a technician dictating at the bay")
    p.box(LX, g + 62, LW, 56, S_STD, "Typed update",
          "the same pipeline, no audio leg")
    p.box(LX, g + 124, LW, 56, S_STD, "Manager question",
          "natural language, console or API")

    p.box(LX, Y0 + 220, LW, 26, S_BANDL, "Knowledge Corpora")
    g = Y0 + 250
    p.box(LX, g, LW, 52, S_STD, "Repair orders · 400",
          "vehicle, pay type, promised time")
    p.box(LX, g + 58, LW, 52, S_STD, "Shift updates · 1,949",
          "technician prose + ground truth")
    p.box(LX, g + 116, LW, 52, S_STD, "Labour operations · 104",
          "op code, flat rate, safety flag")
    p.box(LX, g + 174, LW, 52, S_STD, "Staff · 50",
          "role, skill, shift, team")

    # -------------------------------------------------------------- centre
    lanes = [
        ("1 · CAPTURE &amp; UNDERSTANDING", [
            (S_NVB, "Riva · Parakeet ASR", "speech to text, streaming or offline"),
            (S_NVB, "Nemotron Nano 8B", "technician prose → strict JSON"),
            (S_STD, "Entity resolver", "repair orders, op codes, spoken digits"),
            (S_STD, "Reconciler", "new facts vs the current snapshot"),
        ]),
        ("2 · EVENT LOG &amp; DERIVED STATE", [
            (S_STD, "Event log", "append-only · 10,927 events"),
            (S_STD, "Fold engine", "state derived on read, never stored"),
            (S_STD, "Lifecycle gate", "13 states; illegal moves rejected"),
            (S_STD, "Diff card", "what changed, since when, by whom"),
        ]),
        ("3 · DATA PREPARATION &amp; INDEXING", [
            (S_NV, "NeMo Curator", "6 stages · injection quarantine"),
            (S_NVB, "NV-EmbedQA E5 v5", "1024-dimension embeddings"),
            (S_STD, "Milvus", "COSINE · AUTOINDEX · exact at this size"),
            (S_STD, "Index audit", "staleness, exclusions, re-index"),
        ]),
        ("4 · RETRIEVAL &amp; GROUNDING", [
            (S_STD, "Vector search", "top-k candidates over the updates"),
            (S_NVB, "NV-RerankQA Mistral 4B", "relevance reorder"),
            (S_STD, "Context assembly", "passages the answer may use"),
            (S_STD, "Citation set", "every claim tied to an update id"),
        ]),
        ("5 · REASONING &amp; ANSWERING", [
            (S_STD, "Query planner", "picks the tool; 24 of 24 without a model"),
            (S_NV, "NeMo Switchyard", "nano local ⇄ Nemotron Super hosted"),
            (S_STD, "Tool layer · 10 tools", "deterministic SQL and vector reads"),
            (S_STD, "Answer composers", "every figure computed, not generated"),
            (S_NVB, "Nemotron narration", "prose only, from tool payloads"),
        ]),
        ("6 · GUARDRAILS &amp; VERIFICATION", [
            (S_NV, "NeMo Guardrails", "self check input, on the local NIM"),
            (S_STD, "Injection &amp; scope rail", "pre-model, always on"),
            (S_STD, "Grounding rail", "digits and decimals vs the payload"),
            (S_STD, "Release-claim rail", "authorisation claims need evidence"),
        ]),
    ]
    y = Y0 + 32
    for header, items in lanes:
        p.box(CX, y, CW, 26, S_LANE, header)
        row(p, CX, y + 29, CW, 62, items)
        y += 111

    # --------------------------------------------------------------- right
    p.box(RX, Y0, RW, 26, S_BANDL, "Analyst Experience")
    g = Y0 + 30
    p.box(RX, g, RW, 56, S_STD, "Operations console · 6 tabs",
          "dashboard, RO, update, handover, assistant")
    p.box(RX, g + 62, RW, 56, S_STD, "Review workbench · 7 panes",
          "event log, fold, vectors, retrieval, answers")
    p.box(RX, g + 124, RW, 56, S_STD, "HTTP API · 27 routes",
          "same rails as the console")

    p.box(RX, Y0 + 220, RW, 26, S_BANDL, "Observability")
    g = Y0 + 250
    p.box(RX, g, RW, 52, S_NVB, "NVIDIA DCGM",
          "19 GPU series: utilisation, VRAM, power")
    p.box(RX, g + 58, RW, 52, S_STD, "Prometheus · 13 app series",
          "answers, latency, rails, NIM errors")
    p.box(RX, g + 116, RW, 52, S_STD, "Grafana · 11 panels",
          "provisioned, including the GPU row")
    p.box(RX, g + 174, RW, 52, S_STD, "Store browsers",
          "Attu and sqlite-web, loopback only")

    # ------------------------------------------------- traceability band
    BY = Y0 + 32 + 6 * 111 + 14
    p.box(40, BY, 1620, 26, S_BAND, "TRACEABILITY, ASSURANCE &amp; GOVERNANCE")
    row(p, 40, BY + 30, 1620, 66, [
        (S_STD, "Answer log · 601",
         "what was asked, what it cited, whether it was grounded"),
        (S_NV, "NeMo Relay",
         "per-stage trace spans: tool, model, timing"),
        (S_NV, "NeMo Evaluator",
         "six measures as BYOB benchmarks, run over run"),
        (S_NVB, "Riva · Magpie TTS",
         "synthesises the spoken updates the ASR leg is tested with"),
        (S_STD, "Acceptance gates",
         "routing 90 · grounding 100 · refusal 100 · recall 60"),
    ], pad=0, gap=12)

    # -------------------------------------------------------- infra band
    IY = BY + 110
    p.box(40, IY, 170, 44, S_BANDL, "Infrastructure")
    row(p, 216, IY, 1444, 44, [
        (S_NVB + "align=center;spacingLeft=0;verticalAlign=middle;fontStyle=1;",
         "NVIDIA Brev\nL40S 48 GB", ""),
        (S_NVB + "align=center;spacingLeft=0;verticalAlign=middle;fontStyle=1;",
         "NIM containers\nLLM · embed · rerank", ""),
        (S_NVB + "align=center;spacingLeft=0;verticalAlign=middle;fontStyle=1;",
         "NVIDIA API Catalog\nhosted speech, escalation", ""),
        (S_STD + "align=center;spacingLeft=0;verticalAlign=middle;",
         "Milvus standalone", ""),
        (S_STD + "align=center;spacingLeft=0;verticalAlign=middle;",
         "SQLite system of record", ""),
    ], pad=0, gap=10)

    # ---------------------------------------------- not-integrated strip
    NY = IY + 54
    p.box(40, NY, 170, 28, S_BANDL, "Not integrated")
    p.box(216, NY, 1444, 28, S_ROAD + "align=left;verticalAlign=middle;",
          "NemoClaw / OpenShell — containment boundary and a sandboxed compute "
          "tool. Blocked by a platform fault on the gateway launchable, not "
          "by this project. The one NVIDIA component of fourteen that is "
          "not running.")

    LY = NY + 42
    p.raw(40, LY, 1620, 40, S_NOTE,
          '<b>Green is NVIDIA.</b>&nbsp; '
          '<font style="color:#5B8C3A;">█</font>&nbsp;filled = served model or '
          'NVIDIA infrastructure &nbsp;&nbsp;'
          '<font style="color:#76B900;">▢</font>&nbsp;outlined = NVIDIA '
          'framework or library &nbsp;&nbsp;'
          '<font style="color:#AEB7AC;">▢</font>&nbsp;plain = this project\'s '
          'code, the console and the datastores &nbsp;&nbsp;'
          '<font style="color:#76B900;">⬚</font>&nbsp;dashed = present, not '
          'integrated'
          '<br><font style="font-size:10px;">Nothing in the answer path calls '
          'a hosted model. Speech is the one hosted dependency, because there '
          'is no Riva container in this deployment.</font>')

    # flow arrows, in the gutters
    p.raw(LX + LW + 4, Y0 + 170, 36, 40,
          "shape=singleArrow;direction=east;whiteSpace=wrap;html=1;"
          f"fillColor=#FFFFFF;strokeColor={NVGRN};strokeWidth=2;", "")
    p.raw(CX + CW + 4, Y0 + 170, 36, 40,
          "shape=singleArrow;direction=east;whiteSpace=wrap;html=1;"
          f"fillColor=#FFFFFF;strokeColor={NVGRN};strokeWidth=2;", "")
    return p


def _title(p, w, head, sub):
    p.raw(40, 12, w, 38, S_TITLE, f"<b>{head}</b>")
    p.raw(40, 52, w, 28,
          S_TITLE.replace("fontSize=20", "fontSize=12")
                 .replace("fontColor=#101814", "fontColor=#4A5A52"), sub)


# ==========================================================================
# PAGE 2 - the write path
# ==========================================================================
def page_write_path() -> Page:
    p = Page("2 · Write path", "write", 1560, 1700)
    _title(p, 1400, "WRITE PATH",
           "one spoken or typed update, from the shop floor to the event log "
           "and the vector store")

    MX, MW = 440, 340
    SX, SW = 880, 340
    QX, QW = 60, 330

    start = p.box(MX + 70, 110, 200, 46, S_START, "Shift update")
    d_audio = p.box(MX + 60, 192, 220, 72, S_DEC, "spoken, or typed?")
    asr = p.box(SX, 192, SW, 72, S_NVB, "Riva · Parakeet ASR",
                "streaming and offline paths both implemented; the hosted "
                "model is reached over gRPC")
    bad = p.box(SX, 290, SW, 50, S_STD, "Rejected",
                "empty transcript, no words, wrong sample rate")

    extract = p.box(MX, 306, MW, 72, S_NVB, "Nemotron Nano 8B · extraction",
                    "technician prose → strict JSON, repaired and parsed "
                    "before any of it is trusted")
    validate = p.box(MX, 408, MW, 64, S_STD, "Validation",
                     "types, hour ranges, enum membership")
    resolve = p.box(MX, 502, MW, 84, S_STD, "Entity resolution",
                    "spoken digits, shop aliases and position words; op codes "
                    "matched against the 104-row catalogue, embedding-assisted")

    d_res = p.box(MX + 60, 616, 220, 72, S_DEC, "repair order resolved?")
    clarify = p.box(SX, 616, SW, 88, S_STD, "Clarifying questions",
                    "returned to the speaker. Nothing is written and nothing "
                    "is guessed — a partial resolution still proceeds with "
                    "what did resolve")

    recon = p.box(MX, 734, MW, 64, S_STD, "Reconciliation",
                  "new facts against the current snapshot")
    d_conf = p.box(MX + 60, 828, 220, 72, S_DEC, "contradicts the snapshot?")
    conflict = p.box(SX, 828, SW, 72, S_STD, "Contradiction surfaced",
                     "shown, never silently clobbered. Accepting one is an "
                     "explicit operator act, not a default")

    append = p.box(MX, 944, MW, 64, S_STD, "Append to the event log",
                   "append-only; the only table state is folded from")
    fold = p.box(MX, 1038, MW, 72, S_STD, "Fold → repair-order snapshot",
                 "state derived from the log, never stored as truth. An "
                 "illegal transition is rejected and reported")
    card = p.box(MX, 1140, MW, 58, S_STD, "Diff card",
                 "what changed, since when, by whom")
    curate = p.box(MX, 1228, MW, 72, S_NV, "NeMo Curator · quarantine",
                   "drops notes that address the model rather than the "
                   "record, before they are ever embedded")
    embed = p.box(MX, 1330, MW, 58, S_NVB, "NV-EmbedQA E5 v5",
                  "1024-dimension embeddings")
    upsert = p.box(MX, 1418, MW, 58, S_STD, "Milvus upsert",
                   "COSINE · AUTOINDEX · strong consistency")
    done = p.box(MX + 70, 1508, 200, 46, S_END, "Searchable")

    for a, b in ((start, d_audio), (asr, extract), (extract, validate),
                 (validate, resolve), (resolve, d_res), (recon, d_conf),
                 (append, fold), (fold, card), (card, curate),
                 (curate, embed), (embed, upsert), (upsert, done)):
        p.edge(a, b)
    p.edge(d_audio, asr, E_MAIN, "spoken")
    p.edge(d_audio, extract, E_MAIN, "typed")
    p.edge(asr, bad, E_SIDE, "fails")
    p.edge(d_res, clarify, E_SIDE, "no")
    p.edge(d_res, recon, E_MAIN, "yes")
    p.edge(d_conf, conflict, E_SIDE, "yes")
    p.edge(d_conf, append, E_MAIN, "no")

    p.box(QX, 160, QW, 150, S_NOTE, "Two principles",
          "COMPUTE DETERMINISTICALLY, NARRATE WITH THE MODEL. The model turns "
          "prose into JSON on the way in and JSON into prose on the way out. "
          "It never counts, never infers state and never does arithmetic.\n\n"
          "UPDATES ARE EVENTS, NOT OVERWRITES. A complete audit trail, and "
          "contradictions surface instead of being clobbered.")
    p.box(QX, 340, QW, 112, S_NOTE, "The model is fenced in",
          "Every field a technician can influence is untrusted input. The "
          "extraction is parsed, type-checked and range-checked before any of "
          "it reaches the database, and free text is carried as data rather "
          "than as instructions.")
    p.box(QX, 1228, QW, 126, S_NOTE, "Why curate a clean corpus",
          "Five of the six stages remove nothing, which is the honest result "
          "for generated data. The sixth earns the pipeline: it removes the "
          "injection vector before indexing, so the retriever can never "
          "surface it. The known payload is caught with zero false positives "
          "across 1,949 notes.")
    return p


# ==========================================================================
# PAGE 3 - the read path
# ==========================================================================
def page_read_path() -> Page:
    p = Page("3 · Read path", "read", 1620, 1580)
    _title(p, 1480, "READ PATH",
           "a question becomes a cited answer — rails, plan, tool, composer "
           "or narration, verification")

    MX, MW = 480, 380
    LX, LW = 60, 370
    RX, RW = 1000, 380
    h, step = 68, 96
    y = 112

    def main(style, t, s=""):
        nonlocal y
        cid = p.box(MX, y, MW, h, style, t, s)
        y += step
        return cid

    start = p.box(MX + 90, y, 200, 46, S_START, "Question")
    y += 90

    rails_in = main(S_STD, "Pattern rails — always on, before any model",
                    "prompt injection, out of scope, unauthorised instruction")
    nemo = main(S_NV, "NeMo Guardrails · self check input",
                "a prompt task judged by the local Nemotron NIM — one call, "
                "about 45 ms. Measured 4/4 adversarial blocked, 24/24 "
                "legitimate allowed")
    refused = p.box(RX, y - step, RW, h, S_STD, "Refusal",
                    "no tool runs and no model narrates; the block is counted")

    plan = main(S_STD, "Query planner",
                "keyword-first. The model router exists and is deliberately "
                "not paid for: the planner already routes 24 of 24")
    switch = main(S_NV, "NeMo Switchyard",
                  "nano locally, Nemotron Super hosted on escalation. Off "
                  "unless the deployment turns it on")
    tool = main(S_STD, "Tool layer · one of 10 typed tools",
                "deterministic SQL and vector reads. No subprocess, no eval "
                "of model output, no model-directed sockets")

    d_search = p.box(MX + 80, y, 220, 72, S_DEC, "free-text search?")
    y += 108

    rend = p.box(LX, y, LW, 92, S_STD, "Answer composers",
                 "one per tool shape. Every count, date and booked-hour "
                 "figure is computed in Python from the event log, so these "
                 "paths make no model call at all")
    ms = p.box(RX, y, RW, h, S_STD, "Milvus vector search",
               "top-k candidates from the updates collection")
    rr = p.box(RX, y + 96, RW, h, S_NVB, "NV-RerankQA Mistral 4B",
               "reorders to the passages actually used")
    narr = p.box(RX, y + 192, RW, h + 10, S_NVB, "Nemotron narration",
                 "the one question class a model answers: summarising what "
                 "technicians wrote. Asked for prose, never for a figure")
    y += 308

    ground = main(S_STD, "Grounding check",
                  "every digit and decimal in the text must appear in the "
                  "tool payload. Decimals matter most — booked hours are what "
                  "a manager acts on")
    neg = main(S_STD, "Negation check",
               "a flipped &quot;not&quot; inverts the meaning of a safety "
               "answer")
    outr = main(S_STD, "Release-claim rail",
                "is &quot;approved for release&quot; supported by the "
                "payload, or invented? This runs in code because it needs the "
                "payload — a prose rail cannot see it")
    ans = main(S_STD, "Answer + citations",
               "every claim tied to a repair order and an update id")

    log = p.box(LX, y - step + 2, LW, h, S_STD, "Answer log · 601",
                "question, route, tools, citations, grounded, seconds")
    met = p.box(RX, y - step + 2, RW, h, S_NV, "NeMo Relay + Prometheus",
                "per-stage trace spans and the counters behind the dashboard")
    end = p.box(MX + 90, y, 200, 46, S_END, "Answer")

    p.edge(start, rails_in)
    p.edge(rails_in, nemo)
    p.edge(nemo, refused, E_SIDE, "blocked")
    p.edge(nemo, plan, E_MAIN, "allowed")
    p.edge(plan, switch)
    p.edge(switch, tool)
    p.edge(tool, d_search)
    p.edge(d_search, rend, E_MAIN, "no — 5 of 6 classes")
    p.edge(d_search, ms, E_MAIN, "yes")
    p.edge(ms, rr)
    p.edge(rr, narr)
    p.edge(rend, ground)
    p.edge(narr, ground)
    p.edge(ground, neg)
    p.edge(neg, outr)
    p.edge(outr, ans)
    p.edge(ans, log, E_FEED)
    p.edge(ans, met, E_FEED)
    p.edge(ans, end)

    p.box(LX, 120, LW, 124, S_NOTE, "The flywheel",
          "Every answer is logged with the payload it was built from. Those "
          "rows become a dataset, NeMo Evaluator scores it in its own result "
          "schema, and the scores gate the next change. The agent's own "
          "output is what measures it.")
    p.box(LX, 262, LW, 110, S_NOTE, "Where the model is not",
          "Five of six question classes never reach a model. That is not a "
          "cost saving — it is the reason the figures can be trusted and the "
          "reason the deterministic measures sit at a 100% floor rather than "
          "a hopeful one.")
    return p


# ==========================================================================
# PAGE 4 - the NVIDIA component inventory
# ==========================================================================
# (component, what it does HERE, the thing itself, status, style)
COMPONENTS = [
    ("NIM — LLM", "Turns technician prose into strict JSON on the way in, and "
     "tool payloads into prose on the way out. Nothing else.",
     "Nemotron Nano 8B · served locally on :8000", "running", S_NVB),
    ("NIM — Embedding", "Vectors for all 1,949 updates, and for matching "
     "spoken work against the operation catalogue.",
     "NV-EmbedQA E5 v5 · 1024-dim · :8001", "running", S_NVB),
    ("NIM — Reranking", "Reorders vector candidates to the passages the "
     "answer actually cites.",
     "NV-RerankQA Mistral 4B · :8002", "running", S_NVB),
    ("Riva — ASR", "Speech to text for spoken shift updates. Streaming and "
     "offline paths both implemented.",
     "Parakeet CTC 0.6B · hosted over gRPC", "running", S_NVB),
    ("Riva — TTS", "Synthesises the spoken updates the ASR leg is tested "
     "with. Replaced the operating system's own voice, which was the last "
     "non-NVIDIA model in the speech path.",
     "Magpie TTS Multilingual · hosted over gRPC", "running", S_NVB),
    ("NeMo Agent Toolkit", "A second front end onto the same ten tools, one "
     "toolkit function type each. Five of six question classes answer with "
     "citations; free-text search exhausts the ReAct loop budget on the 8B.",
     "NeMo Agent Toolkit workflow", "running · 5 of 6 classes", S_NV),
    ("NeMo Guardrails", "The input rail, judged by the local model against "
     "this project's own safety policy rather than a generic one.",
     "self check input rail", "running", S_NV),
    ("NeMo Curator", "Six-stage curation. Five find nothing in generated "
     "data; the sixth quarantines the injection vector before indexing.",
     "heuristic filters + a custom quarantine stage", "running", S_NV),
    ("NeMo Evaluator", "The six measures as BYOB benchmarks, emitted in "
     "Evaluator's own result schema so one run is comparable with the last.",
     "BYOB benchmarks, scored from recorded answers", "running", S_NV),
    ("NeMo Relay", "Records how an answer was produced — which tool, which "
     "model, how long each span took — rather than only what it said.",
     "tool and model intercepts", "running", S_NV),
    ("NeMo Switchyard", "Routing proxy: the efficient model locally, the "
     "capable one hosted when something raises confidence.",
     "nano local ⇄ Nemotron Super hosted", "configured, off by default", S_NV),
    ("NVIDIA DCGM", "GPU telemetry — utilisation, framebuffer, power, "
     "temperature, clocks. Three NIMs co-reside in 40 GB of 48; this is "
     "where that stops being a claim.",
     "DCGM exporter · 19 series · :9401", "running", S_NVB),
    ("Milvus", "The vector store. Standalone on the box, browsable, and "
     "rebuildable from the event log.",
     "Milvus standalone · :19530",
     "running — not an NVIDIA product, but the store in NVIDIA's own RAG "
     "reference stack", S_STD),
    ("NVIDIA Brev", "The deployment target. One L40S carrying all three NIMs "
     "and everything else.",
     "L40S 48 GB", "running", S_NVB),
    ("NemoClaw / OpenShell", "Would add a containment boundary and a "
     "sandboxed compute tool, so derived figures could be computed rather "
     "than narrated.",
     "agent sandbox gateway", "BLOCKED — platform fault", S_ROAD),
]


def page_components() -> Page:
    p = Page("4 · NVIDIA components", "comp", 1620, 1360)
    _title(p, 1480, "NVIDIA COMPONENT INVENTORY",
           "thirteen NVIDIA components running, one blocked — every status "
           "here measured by running the thing, not by importing it")

    cols = [(40, 230), (278, 480), (766, 400), (1174, 406)]
    for (x, w), hname in zip(cols, ["COMPONENT", "WHAT IT DOES HERE",
                                    "THE COMPONENT", "STATUS"]):
        p.box(x, 86, w, 24, S_LANE, hname)

    y = 116
    for name, role, thing, status, style in COMPONENTS:
        hgt = 74 if len(role) > 95 else 58
        p.box(cols[0][0], y, cols[0][1], hgt,
              style + "verticalAlign=middle;", name)
        p.raw(cols[1][0], y, cols[1][1], hgt, S_STD + "verticalAlign=middle;",
              f'<font style="font-size:11px;">{role}</font>')
        p.raw(cols[2][0], y, cols[2][1], hgt, S_STD + "verticalAlign=middle;",
              f'<font style="font-size:10.5px;">{thing}</font>')
        blocked = status.startswith("BLOCKED")
        p.raw(cols[3][0], y, cols[3][1], hgt,
              (S_ROAD if blocked else style) + "verticalAlign=middle;",
              f'<font style="font-size:10.5px;">'
              f'{"<b>" + status + "</b>" if blocked else status}</font>')
        y += hgt + 5

    p.box(40, y + 10, 1540, 96, S_NOTE,
          "What the one blocked row actually costs",
          "A containment boundary, and a sandboxed compute tool that would let "
          "derived figures be computed rather than narrated. It is not in the "
          "answer path: the agent the console and the API call is this "
          "project's own router, and it is the one every measure on this page "
          "was taken against. Nothing in it executes untrusted code — the ten "
          "tools are deterministic SQL and vector reads, with no subprocess, "
          "no evaluation of model output and no model-directed network calls.")
    return p


# ==========================================================================
# PAGE 5 - deployment
# ==========================================================================
def page_deployment() -> Page:
    p = Page("5 · Deployment and ports", "dep", 1520, 1120)
    _title(p, 1400, "DEPLOYMENT",
           "one Brev L40S. All three NIMs co-reside in roughly 40 GB of the "
           "48 — which is why escalation leaves the box rather than loading a "
           "second local model")

    p.box(40, 92, 1440, 28, S_BAND, "NVIDIA BREV · L40S 48 GB")

    p.box(60, 140, 1400, 24, S_LANE, "GPU — served models")
    row(p, 60, 170, 1400, 72, [
        (S_NVB, "LLM NIM · :8000", "Nemotron Nano 8B · about 22.5 GB · "
         "OpenAI-compatible chat completions"),
        (S_NVB, "Embedding NIM · :8001", "NV-EmbedQA E5 v5 · 1024 dimensions"),
        (S_NVB, "Reranking NIM · :8002", "NV-RerankQA Mistral 4B · no hosted "
         "equivalent exists"),
    ], pad=0, gap=14)

    p.box(60, 262, 1400, 24, S_LANE, "GPU — telemetry")
    p.box(70, 292, 1380, 50, S_NVB, "NVIDIA DCGM exporter · :9401",
          "utilisation, framebuffer, power, temperature and clocks, scraped "
          "every 10 seconds. 9401 because the application already holds 9400.")

    p.box(60, 362, 1400, 24, S_LANE, "Datastores")
    row(p, 60, 392, 1400, 72, [
        (S_STD, "Milvus standalone · :19530", "the vector store; metrics on "
         ":9091"),
        (S_STD, "SQLite — system of record", "every application read is "
         "read-only except the single writer"),
        (S_STD, "An unused embedded store", "present and NOT in use — the "
         "startup report names it so it cannot be mistaken for the live one "
         "again"),
    ], pad=0, gap=14)

    p.box(60, 484, 1400, 24, S_LANE, "Application")
    row(p, 60, 514, 1400, 66, [
        (S_STD, "HTTP API · :8080", "27 routes, OpenAPI at /docs"),
        (S_STD, "Operations console · :7860", "6 tabs, optional public link"),
        (S_STD, "Metrics exporter · :9400", "separate from the API port, "
         "which is why :8080/metrics is a 404"),
    ], pad=0, gap=14)

    p.box(60, 600, 1400, 24, S_LANE,
          "Operator surfaces — bound to loopback, reached over one SSH forward")
    row(p, 60, 630, 1400, 66, [
        (S_STD, "Prometheus · :9090", "named volume; retention survives a "
         "recreate"),
        (S_STD, "Grafana · :3000", "provisioned dashboard, GPU row included"),
        (S_STD, "Attu · :8101", "the Milvus browser"),
        (S_STD, "sqlite-web · :8102", "the system-of-record browser"),
    ], pad=0, gap=14)

    p.box(60, 716, 680, 112, S_NOTE, "One command up, one command down",
          "Milvus first, because the API reads the store; then the NIMs, the "
          "API, the console, the store browsers, DCGM and the observability "
          "stack. Every start prints a report naming which store is actually "
          "serving, so the question &quot;which database am I looking "
          "at?&quot; is answered before it is asked.")
    p.box(760, 716, 700, 112, S_NOTE, "Why the vector browser needs a container IP",
          "Milvus sits on docker's default bridge, which has no embedded DNS, "
          "and a container reaching the published port on the gateway address "
          "times out on this box. So the launcher resolves the container IP at "
          "start and recreates the browser if it has moved. Diagnosed rather "
          "than guessed; the alternative was a browser that silently showed an "
          "empty store.")

    p.box(60, 848, 1400, 24, S_LANE, "Exposure")
    p.box(60, 878, 1400, 88, S_NOTE, "What is reachable from outside the box",
          "The optional public console link, and nothing else. The API, the "
          "vector store, Grafana, Prometheus and both store browsers are not "
          "exposed beyond the instance; the operator surfaces are "
          "loopback-bound and reached with an SSH forward. The API key lives "
          "in an ignored environment file, is never committed and is never "
          "printed — the stack verifies the line length after every edit "
          "rather than echoing the value.")
    return p


# ==========================================================================
# PAGE 6 - the data model
# ==========================================================================
S_TBL = ("rounded=0;whiteSpace=wrap;html=1;align=left;verticalAlign=top;"
         "spacing=6;spacingLeft=8;fontSize=11;")


def _table(p: Page, x, y, w, name, rows, cols, style_fill, note=""):
    body = "<br>".join(
        f'<font style="font-family:Courier New;font-size:10px;">{c}</font>'
        for c in cols)
    head = (f'<b>{name}</b>'
            f'<font style="font-size:10px;color:#55707E;"> · {rows}</font>'
            f'<br><font style="font-size:3px;"><br></font>{body}')
    if note:
        head += (f'<br><font style="font-size:3px;"><br></font>'
                 f'<font style="font-size:9.5px;color:#55707E;">{note}</font>')
    # 15px per 10px Courier line, plus a wrapped note measured at ~5.4px per
    # character. Overestimating is free; a clipped column list is not.
    nl = 0
    if note:
        plain = re.sub(r"<[^>]+>", "", note)
        nl = max(1, -(-len(plain) // max(1, int(w / 5.4))))
    h = 40 + 15 * len(cols) + (16 + 12 * nl if note else 0)
    return p.raw(x, y, w, h, S_TBL + style_fill, head)


def page_data_model() -> Page:
    p = Page("6 · Data model", "data", 1500, 1060)
    p.raw(40, 20, 1420, 52, S_TITLE,
          '<b>DATA MODEL</b><font style="font-size:12px;color:#55707E;">'
          '&nbsp;&nbsp;·&nbsp;&nbsp;SQLite is the system of record; Milvus '
          'is derived from it and can always be rebuilt. Row counts read '
          'from the running box</font>')

    # Same legend as every other page: green is NVIDIA, plain is not.
    F_SRC = f"fillColor={PAPER};strokeColor={EDGE};strokeWidth=1;fontColor=#1C2B25;"
    F_DER = f"fillColor=#FFFFFF;strokeColor={NVGRN};strokeWidth=2;fontColor=#17301A;"
    F_AUD = F_SRC

    p.box(40, 92, 900, 26, S_LANE, "SYSTEM OF RECORD")
    p.box(970, 92, 490, 26, S_LANE, "DERIVED — rebuildable from the log")

    ros = _table(p, 60, 134, 290, "ros", "400 rows",
                 ["ro_number  PK", "vin · registration", "make · model · model_year",
                  "engine · odometer_miles", "pay_type · wait_type",
                  "checked_in_at · promised_time", "advisor_id  → staff",
                  "primary_tech_id  → staff", "concern · category"], F_SRC)
    staff = _table(p, 60, 400, 290, "staff", "50 rows",
                   ["staff_id  PK", "name · role", "skill · shift · team"],
                   F_SRC)
    ops = _table(p, 60, 530, 290, "labour_ops", "104 rows",
                 ["op_code  PK", "description · category",
                  "flat_rate_hrs · min_skill", "safety_critical"], F_SRC,
                 "The catalogue resolve_op() matches against.")
    upd = _table(p, 400, 134, 300, "updates", "1,949 rows",
                 ["update_id  PK", "ro_number  → ros", "staff_id  → staff",
                  "at · shift", "text", "ground_truth"], F_SRC,
                 "What a technician said. &quot;text&quot; is untrusted "
                 "input and is treated as such everywhere.")
    ev = _table(p, 400, 360, 300, "events", "10,927 rows",
                ["event_id  PK", "ro_number  → ros", "type · at",
                 "actor_id  → staff", "shift",
                 "source_update_id  → updates", "payload  (json)"], F_SRC,
                "Append-only. The only table state is folded from.")
    aud = _table(p, 400, 620, 300, "index_audit", "8 rows",
                 ["audit_id  PK", "update_id · ro_number", "kind · at",
                  "actor_id · payload"], F_AUD,
                 "Who re-indexed or excluded what, and when.")
    exc = _table(p, 400, 790, 300, "index_exclusions", "0 rows",
                 ["update_id  PK", "at · actor_id · reason"], F_AUD)
    ans = _table(p, 60, 720, 290, "answer_log", "601 rows",
                 ["answer_id  PK · at", "question · answer", "route · composed",
                  "grounded · tools", "citations · warnings", "seconds"],
                 F_AUD, "The flywheel's raw material.")

    mil = _table(p, 990, 134, 440, "Milvus collection &quot;updates&quot;",
                 "one row per update",
                 ["pk  INT64  PK", "vector  FLOAT_VECTOR(1024)",
                  "update_id · ro_number", "staff_id · staff_name",
                  "at · shift", "text  VARCHAR(8192)",
                  "vehicle · category · concern · vin"], F_DER,
                 "AUTOINDEX, COSINE, strong consistency. AUTOINDEX picks FLAT "
                 "at this size — exact, not approximate; at two thousand rows "
                 "an ANN index would trade recall for nothing.")
    snap = _table(p, 990, 430, 440, "RO snapshot", "computed, never stored",
                  ["state  (1 of 13)", "blocking · at_risk · safety flags",
                   "booked hours · assigned tech",
                   "contradictions outstanding"], F_DER,
                  "Folded from events on every read. There is no status "
                  "column anywhere that could drift from the log.")

    for a, b in ((upd, ros), (ev, ros), (ev, upd), (ros, staff), (upd, staff),
                 (ev, staff), (aud, upd), (exc, upd)):
        p.edge(a, b, E_MAIN + "endArrow=open;endFill=0;strokeWidth=1.2;")
    p.edge(upd, mil, E_FEED, "embed + upsert")
    p.edge(ev, snap, E_FEED, "fold")

    p.box(730, 620, 240, 168, S_NOTE, "Why derived means rebuildable",
          "Milvus holds no fact that SQLite does not. Dropping the "
          "collection and re-running the index loses nothing, which is what "
          "makes editing the vector store safe to offer at all.\n\n"
          "The reverse is not true: events can never be rebuilt from "
          "anything, which is why they are append-only and why every "
          "application read of the SQLite file is opened mode=ro.")
    return p


# ==========================================================================
# PAGE 7 - the repair order lifecycle
# ==========================================================================
STATES = {
    "CHECKED_IN": (60, 130), "DISPATCHED": (300, 130),
    "DIAGNOSING": (540, 130), "ESTIMATE_PREPARED": (780, 130),
    "AWAITING_AUTHORISATION": (1020, 130), "AUTHORISED": (1260, 130),
    "PARTS_HOLD": (780, 340), "REPAIR_IN_PROGRESS": (1260, 340),
    "QUALITY_CONTROL": (1500, 340), "ROAD_TEST": (1740, 340),
    "READY_FOR_DELIVERY": (1980, 340), "INVOICED": (2220, 340),
    "DECLINED": (1500, 540),
}
LEGAL = {
    "CHECKED_IN": ["DISPATCHED"],
    "DISPATCHED": ["DIAGNOSING", "REPAIR_IN_PROGRESS", "ESTIMATE_PREPARED"],
    "DIAGNOSING": ["ESTIMATE_PREPARED", "REPAIR_IN_PROGRESS", "PARTS_HOLD"],
    "ESTIMATE_PREPARED": ["AWAITING_AUTHORISATION"],
    "AWAITING_AUTHORISATION": ["AUTHORISED", "DECLINED"],
    "AUTHORISED": ["REPAIR_IN_PROGRESS", "PARTS_HOLD"],
    "DECLINED": ["READY_FOR_DELIVERY", "INVOICED"],
    "PARTS_HOLD": ["REPAIR_IN_PROGRESS", "AWAITING_AUTHORISATION"],
    "REPAIR_IN_PROGRESS": ["PARTS_HOLD", "QUALITY_CONTROL",
                           "AWAITING_AUTHORISATION"],
    "QUALITY_CONTROL": ["ROAD_TEST", "REPAIR_IN_PROGRESS"],
    "ROAD_TEST": ["READY_FOR_DELIVERY", "REPAIR_IN_PROGRESS"],
    "READY_FOR_DELIVERY": ["INVOICED"],
    "INVOICED": [],
}
BLOCKING = {"AWAITING_AUTHORISATION", "PARTS_HOLD"}
TERMINAL = {"INVOICED"}


def page_lifecycle() -> Page:
    p = Page("7 · Repair order lifecycle", "life", 2560, 840)
    _title(p, 2400, "REPAIR ORDER LIFECYCLE",
           "13 states, and only these transitions. Anything absent is "
           "rejected by the engine and surfaced, never silently applied")

    S_ST = ("rounded=0;whiteSpace=wrap;html=1;align=center;"
            "verticalAlign=middle;fontSize=11;fontStyle=1;strokeWidth=1;"
            f"fillColor={PAPER};strokeColor={EDGE};fontColor=#1C2B25;")
    # The two blocking states are the point of the whole lifecycle, so they
    # are the only ones that get emphasis.
    S_BL = ("rounded=0;whiteSpace=wrap;html=1;align=center;"
            "verticalAlign=middle;fontSize=11;fontStyle=1;strokeWidth=2;"
            f"fillColor=#FAEADF;strokeColor={ACCENT_O};fontColor=#3A2114;")
    S_TE = ("rounded=0;whiteSpace=wrap;html=1;align=center;"
            "verticalAlign=middle;fontSize=11;fontStyle=1;strokeWidth=2;"
            f"fillColor={NVSOLID};strokeColor=#446B29;fontColor=#FFFFFF;")

    ids = {}
    for name, (x, y) in STATES.items():
        style = S_BL if name in BLOCKING else (
            S_TE if name in TERMINAL else S_ST)
        sub = ("vehicles sit here" if name in BLOCKING else
               "terminal" if name in TERMINAL else "")
        ids[name] = p.box(x, y, 200, 56, style, name, sub)

    for src, dsts in LEGAL.items():
        for dst in dsts:
            p.edge(ids[src], ids[dst], E_MAIN + "strokeWidth=1.3;")

    p.box(60, 540, 600, 72, S_NOTE,
          "Deliberately not IN_PROGRESS / COMPLETE",
          "The states that matter operationally are the blocking ones — "
          "AWAITING_AUTHORISATION and PARTS_HOLD — because that is where "
          "vehicles actually sit, and surfacing them is where the agent "
          "creates value. A two-state lifecycle would have been easier to "
          "model and would have had nothing to say.")
    p.box(700, 540, 600, 72, S_NOTE,
          "The authorisation rule",
          "REPAIR_IN_PROGRESS requires authorisation: work cannot "
          "legitimately begin before the customer has said yes. That rule is "
          "why the output rail exists — &quot;RO-… is approved for "
          "release&quot; is a claim about this gate, and it must come from "
          "the event log rather than from a model's turn of phrase.")
    p.box(1740, 540, 700, 72, S_NOTE,
          "QC failure is a real edge, not an error path",
          "QUALITY_CONTROL → REPAIR_IN_PROGRESS and ROAD_TEST → "
          "REPAIR_IN_PROGRESS both exist, as does REPAIR_IN_PROGRESS → "
          "AWAITING_AUTHORISATION for supplementary work found mid-repair. "
          "A lifecycle that only moves forward does not describe a workshop.")
    return p


PAGES = (page_architecture, page_write_path, page_read_path, page_components,
         page_deployment, page_data_model, page_lifecycle)


def build() -> str:
    pages = "\n".join(fn().render() for fn in PAGES)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<mxfile host="app.diagrams.net" type="device" '
            'agent="scripts/make_architecture_diagram.py" version="24.7.17">\n'
            f'{pages}\n</mxfile>\n')


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="docs/architecture.drawio")
    args = ap.parse_args()

    xml = build()

    # Parse what we are about to write. A .drawio that does not open is worse
    # than no diagram, and the failure is silent until someone double-clicks it.
    import xml.etree.ElementTree as ET
    root = ET.fromstring(xml)
    diagrams = root.findall("diagram")
    if len(diagrams) != len(PAGES):
        print(f"expected {len(PAGES)} pages, built {len(diagrams)}")
        return 1
    for d in diagrams:
        # Ids are page-scoped in draw.io - "0" and "1" repeat on every page by
        # convention - so uniqueness is checked per page, not across the file.
        seen: set[str] = set()
        for cell in d.iter("mxCell"):
            cid = cell.get("id")
            if cid in seen:
                print(f"{d.get('name')}: duplicate cell id {cid!r}")
                return 1
            seen.add(cid)
        # Every edge must point at cells that exist on its own page, or
        # draw.io drops it without saying so.
        page_ids = seen
        for cell in d.iter("mxCell"):
            if cell.get("edge") != "1":
                continue
            for end in ("source", "target"):
                ref = cell.get(end)
                if ref and ref not in page_ids:
                    print(f"{d.get('name')}: edge {cell.get('id')} "
                          f"{end}={ref} is not on this page")
                    return 1

    d = os.path.dirname(args.out)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(xml)
    cells = sum(1 for _ in root.iter("mxCell")) - 2 * len(PAGES)
    print(f"wrote {args.out}")
    print(f"  {len(diagrams)} pages, {cells} shapes and connectors")
    for dg in diagrams:
        n = sum(1 for _ in dg.iter("mxCell")) - 2
        print(f"    {dg.get('name'):52s} {n:4d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
