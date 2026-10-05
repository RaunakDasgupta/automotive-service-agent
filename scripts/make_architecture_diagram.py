#!/usr/bin/env python3
"""Generate docs/architecture.drawio - the project's architecture as a
multi-page draw.io file.

    .venv/bin/python scripts/make_architecture_diagram.py
    .venv/bin/python scripts/make_architecture_diagram.py --out /tmp/a.drawio

WHY A GENERATOR RATHER THAN A HAND-DRAWN FILE

A diagram drawn once is accurate once. Every box here carries a count, a port,
a model id or a file path, and all of those move. Generating the file from
constants that sit next to the claim they make means a wrong number is a one
line fix and a re-run, not an afternoon of dragging rectangles.

The counts marked VERIFIED were read off the running box on 2026-10-05:
10 tools, 27 HTTP routes, 13 metric series, and the table row counts.

The output is uncompressed draw.io XML, so it is diffable and opens in
app.diagrams.net, the desktop app, or the VS Code extension without a round
trip through a server.
"""
from __future__ import annotations

import argparse
import os
import re
from xml.sax.saxutils import escape as _xesc

# --------------------------------------------------------------------------
# palette. Fill encodes WHAT A THING IS, which is the only legend the reader
# has to learn: green is NVIDIA, blue is our Python, amber is a store.
# --------------------------------------------------------------------------
GREEN = "#76B900"        # NVIDIA components
BLUE = "#3A6EA5"         # project code
AMBER = "#D6B656"        # persistent stores
RED = "#B85450"          # guardrails and verification
PURPLE = "#7E57C2"       # operations / observability
GREY = "#9E9E9E"         # not integrated
INK = "#1D3C4E"          # lane headers
DEEP = "#102A38"         # section bands

_BOX = ("rounded=0;whiteSpace=wrap;html=1;align=left;verticalAlign=top;"
        "spacing=4;spacingLeft=8;spacingTop=2;fontSize=11;strokeWidth=2;")

S_NV = _BOX + f"fillColor=#EDF6DD;strokeColor={GREEN};fontColor=#1C3307;"
S_CODE = _BOX + f"fillColor=#E8EEF7;strokeColor={BLUE};fontColor=#13293D;"
S_STORE = _BOX + f"fillColor=#FFF4D6;strokeColor={AMBER};fontColor=#3D3317;"
S_RAIL = _BOX + f"fillColor=#FBE5E5;strokeColor={RED};fontColor=#3D1414;"
S_OPS = _BOX + f"fillColor=#EFE9F8;strokeColor={PURPLE};fontColor=#271A3D;"
S_OFF = _BOX + f"fillColor=#F4F4F4;strokeColor={GREY};fontColor=#555555;dashed=1;"

S_LANE = ("rounded=0;whiteSpace=wrap;html=1;align=left;verticalAlign=middle;"
          f"spacingLeft=10;fontSize=11;fontStyle=1;fillColor={INK};"
          "strokeColor=none;fontColor=#FFFFFF;")
S_BAND = ("rounded=0;whiteSpace=wrap;html=1;align=left;verticalAlign=middle;"
          f"spacingLeft=12;fontSize=12;fontStyle=1;fillColor={DEEP};"
          "strokeColor=none;fontColor=#FFFFFF;")
S_GROUP = ("rounded=0;whiteSpace=wrap;html=1;align=left;verticalAlign=top;"
           "spacingLeft=10;spacingTop=4;fontSize=11;fontStyle=1;"
           "fillColor=#FAFBFC;strokeColor=#B6C2CC;fontColor=#1D3C4E;"
           "dashed=0;")
S_TITLE = ("rounded=0;whiteSpace=wrap;html=1;align=left;verticalAlign=middle;"
           "spacingLeft=16;fontSize=20;fontStyle=1;fillColor=#FFFFFF;"
           "strokeColor=none;fontColor=#102A38;")
S_NOTE = ("rounded=0;whiteSpace=wrap;html=1;align=left;verticalAlign=top;"
          "spacing=6;fontSize=11;fillColor=#FFFFFF;strokeColor=#C9D3DA;"
          "fontColor=#33474F;")
S_PANEL_L = ("rounded=0;whiteSpace=wrap;html=1;align=left;verticalAlign=top;"
             "spacing=8;fontSize=11;fillColor=#F4F8EC;strokeColor=#76B900;"
             "fontColor=#1C3307;")
S_PANEL_R = ("rounded=0;whiteSpace=wrap;html=1;align=left;verticalAlign=top;"
             "spacing=8;fontSize=11;fillColor=#FDF1EC;strokeColor=#D79B7A;"
             "fontColor=#3D2314;")

S_START = ("ellipse;whiteSpace=wrap;html=1;align=center;verticalAlign=middle;"
           "fontSize=11;fontStyle=1;fillColor=#E8EEF7;strokeColor=#3A6EA5;"
           "strokeWidth=2;fontColor=#13293D;")
S_END = ("ellipse;whiteSpace=wrap;html=1;align=center;verticalAlign=middle;"
         "fontSize=11;fontStyle=1;fillColor=#E3EEDA;strokeColor=#5C8A1E;"
         "strokeWidth=2;fontColor=#1C3307;")
S_DEC = ("rhombus;whiteSpace=wrap;html=1;align=center;verticalAlign=middle;"
         "fontSize=10;fillColor=#FFF4D6;strokeColor=#D6B656;strokeWidth=2;"
         "fontColor=#3D3317;")

E_MAIN = ("edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;jettySize=auto;"
          "strokeColor=#44616F;strokeWidth=1.6;endArrow=block;endFill=1;"
          "fontSize=10;fontColor=#33474F;labelBackgroundColor=#FFFFFF;")
E_SIDE = ("edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;jettySize=auto;"
          "strokeColor=#B85450;strokeWidth=1.4;endArrow=block;endFill=1;"
          "dashed=1;fontSize=10;fontColor=#B85450;"
          "labelBackgroundColor=#FFFFFF;")
E_FEED = ("edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;jettySize=auto;"
          "strokeColor=#7E57C2;strokeWidth=1.4;endArrow=block;endFill=1;"
          "dashed=1;fontSize=10;fontColor=#5E3FA0;"
          "labelBackgroundColor=#FFFFFF;")
E_FAT = ("edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;strokeColor=#76B900;"
         "strokeWidth=3;endArrow=blockThin;endFill=1;")


def esc(s: str) -> str:
    return _xesc(s, {'"': "&quot;"})


def lbl(title: str, sub: str = "") -> str:
    """A bold name over a small grey line. The sub line is where the evidence
    goes - a port, a file, a count - so no box is a noun with nothing behind it."""
    title = title.replace("\n", "<br>")
    out = f"<b>{title}</b>"
    if sub:
        sub = sub.replace("\n", "<br>")
        out += f'<br><font style="font-size:9.5px;color:#55707E;">{sub}</font>'
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
            f'        <mxCell id="{cid}" value="{esc(lbl(title, sub))}" '
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
    p = Page("1 · Architecture", "arch", 1700, 1250)

    p.raw(40, 20, 1620, 52, S_TITLE,
          '<b>AGENTIC AI USE CASE — Automotive Service Operations '
          'Intelligence Agent</b>'
          '<font style="font-size:12px;color:#55707E;">&nbsp;&nbsp;·&nbsp;&nbsp;'
          'voice and text shift updates → derived repair-order state → a '
          'grounded agent</font>')

    p.raw(40, 82, 800, 100, S_PANEL_L,
          '<b style="font-size:13px;">OBJECTIVE</b><br>'
          '<font style="font-size:11px;">A service department\'s true state '
          'lives in what technicians say during the shift, and it is lost: '
          'spoken updates never reach the DMS, the advisor re-walks the shop '
          'to answer "is this car safe to release?", and the handover between '
          'shifts is rebuilt from memory. Status is stale, blocked vehicles '
          'sit unnoticed, and nobody can show how a figure was '
          'arrived at.</font>')

    p.raw(860, 82, 800, 100, S_PANEL_R,
          '<b style="font-size:13px;">BUSINESS OUTCOME</b><br>'
          '<font style="font-size:11px;">'
          '• Capture the shift by speaking, not by typing into a DMS<br>'
          '• Surface blocked and at-risk vehicles the moment they block<br>'
          '• Hand over a shift in one prioritised, cited page<br>'
          '• Every figure computed and traceable to an update id — auditable '
          'by construction<br>'
          '• Runs on one L40S: no customer data leaves the box</font>')

    p.raw(40, 212, 1620, 26, S_BAND,
          'ARCHITECTURE&nbsp;&nbsp;<font style="font-weight:normal;'
          'font-size:10px;">lanes run top to bottom; the write path and the '
          'read path are drawn on pages 2 and 3</font>')

    Y0 = 256
    # Columns leave a 44px gutter on each side of the platform, because the
    # flow arrows live in those gutters rather than on top of a lane.
    LX, LW = 40, 240
    CX, CW = 324, 1000
    RX, RW = 1368, 292

    # ---------------------------------------------------------------- left
    p.box(LX, Y0, LW, 24, S_LANE, "LIVE INPUTS")
    g = Y0 + 28
    p.box(LX, g, LW, 60, S_CODE, "Voice update",
          "16 kHz mono WAV · gr.Audio or POST /updates")
    p.box(LX, g + 66, LW, 60, S_CODE, "Typed update",
          "technician free text, same pipeline")
    p.box(LX, g + 132, LW, 60, S_CODE, "Manager question",
          "natural language · UI tab or POST /ask")

    p.box(LX, Y0 + 226, LW, 24, S_LANE, "SEEDED CORPORA")
    g = Y0 + 254
    p.box(LX, g, LW, 56, S_STORE, "Repair orders · 400",
          "VIN, vehicle, pay type, promised time")
    p.box(LX, g + 62, LW, 56, S_STORE, "Shift updates · 1,949",
          "technician prose + ground truth")
    p.box(LX, g + 124, LW, 56, S_STORE, "Labour operations · 104",
          "op code, flat rate, skill, safety flag")
    p.box(LX, g + 186, LW, 56, S_STORE, "Staff · 50",
          "role, skill, shift, team")

    p.box(LX, Y0 + 508, LW, 92, S_NOTE,
          "Generated, not scraped",
          "app/data/{generate,scenarios,catalog,vin,narrate}.py builds a "
          "shop with realistic failure modes — contradictions, missing "
          "authorisations, parts holds — so the agent has something worth "
          "being right about.")

    # -------------------------------------------------------------- center
    lanes = [
        ("1 · INGESTION &amp; UNDERSTANDING", [
            (S_CODE, "Capture", "app/pipeline/run.py · one entry point"),
            (S_NV, "Riva · Parakeet CTC 0.6B", "ASR over gRPC · nvcf"),
            (S_NV, "Extract — Nemotron Nano 8B", "prose → strict JSON"),
            (S_CODE, "Resolve", "RO digits + op code, embedding-assisted"),
            (S_CODE, "Reconcile", "conflict detection vs snapshot"),
        ]),
        ("2 · EVENT LOG &amp; DERIVED STATE", [
            (S_STORE, "events · append-only", "10,927 rows · never overwritten"),
            (S_CODE, "Fold → RO snapshot", "app/state/engine.py"),
            (S_CODE, "13-state lifecycle", "illegal transitions rejected, not applied"),
            (S_CODE, "Diff card", "what changed, since when, by whom"),
        ]),
        ("3 · DATA PREPARATION &amp; INDEXING", [
            (S_NV, "NeMo Curator", "6 stages · scripts/curate.py"),
            (S_NV, "nv-embedqa-e5-v5", "1024-dim · NIM :8001"),
            (S_STORE, "Milvus upsert", "collection &quot;updates&quot; · COSINE"),
            (S_CODE, "Index audit + exclusions", "staleness, dangling ids, re-index"),
        ]),
        ("4 · RETRIEVAL &amp; GROUNDING", [
            (S_STORE, "Milvus search", "AUTOINDEX · top-k candidates"),
            (S_NV, "nv-rerankqa-mistral-4b-v3", "relevance reorder · NIM :8002"),
            (S_CODE, "Context assembly", "top passages + their update ids"),
            (S_CODE, "Citation set", "[RO-…] [UPD-…] carried to the answer"),
        ]),
        ("5 · REASONING &amp; ANSWERING", [
            (S_CODE, "Planner", "keyword first; LLM router optional"),
            (S_NV, "NeMo Switchyard", "nano local ⇄ super hosted · off by default"),
            (S_CODE, "10 typed tools", "deterministic SQL and vector reads"),
            (S_CODE, "Renderers", "every figure computed in Python"),
            (S_NV, "Nemotron narration", "prose only, from tool payloads"),
        ]),
        ("6 · GUARDRAILS &amp; VERIFICATION", [
            (S_NV, "NeMo Guardrails input rail", "self check input · nano NIM"),
            (S_RAIL, "Injection + scope rails", "regex, pre-model, always on"),
            (S_RAIL, "Grounding rail", "digits and decimals vs payload"),
            (S_RAIL, "Output rail", "unauthorised-release claim check"),
        ]),
    ]
    y = Y0
    lane_ids = []
    for header, items in lanes:
        p.box(CX, y, CW, 24, S_LANE, header)
        ids = row(p, CX, y + 28, CW, 64, items)
        lane_ids.append(ids)
        y += 112

    # --------------------------------------------------------------- right
    p.box(RX, Y0, RW, 24, S_LANE, "ANALYST EXPERIENCE")
    g = Y0 + 28
    p.box(RX, g, RW, 60, S_CODE, "Gradio UI · 6 tabs",
          "dashboard, RO, update, handover, assistant, data")
    p.box(RX, g + 66, RW, 60, S_CODE, "Review workbench · 7 panes",
          "event log, fold, vector store, retrieval, answers")
    p.box(RX, g + 132, RW, 60, S_CODE, "HTTP API · 27 routes",
          "FastAPI :8080 · /ask /updates /review/*")

    p.box(RX, Y0 + 226, RW, 24, S_LANE, "OBSERVABILITY")
    g = Y0 + 254
    p.box(RX, g, RW, 56, S_OPS, "Prometheus · 13 series",
          "counters, histograms, build info")
    p.box(RX, g + 62, RW, 56, S_OPS, "Grafana",
          "latency by stage, rail activity")
    p.box(RX, g + 124, RW, 56, S_OPS, "Attu",
          "vector store browser · loopback :8101")
    p.box(RX, g + 186, RW, 56, S_OPS, "sqlite-web",
          "system of record browser · loopback :8102")

    p.box(RX, Y0 + 508, RW, 92, S_NOTE,
          "Operator surfaces, not app surfaces",
          "The stores are inspectable and mutable, but deliberately outside "
          "the product UI: bound to loopback and reached over one SSH "
          "forward. scripts/stores.sh")

    # ------------------------------------------------- traceability band
    BY = 962
    p.box(40, BY, 1620, 26, S_BAND, "TRACEABILITY, ASSURANCE &amp; GOVERNANCE")
    row(p, 40, BY + 30, 1620, 72, [
        (S_CODE, "Answer log · 601",
         "question, route, tools, citations, grounded, seconds"),
        (S_CODE, "Trace spans",
         "per-stage latency · app/obs/trace.py"),
        (S_NV, "NeMo Evaluator · BYOB",
         "evals/asoia_byob.py — results in Evaluator's own schema"),
        (S_RAIL, "Adversarial suite",
         "4 attack prompts · 100% floor, no exceptions"),
        (S_CODE, "Acceptance floors",
         "routing 90 · grounding 100 · traceability 100 · "
         "refusal 100 · recall 60 · narrated 90"),
    ], pad=0, gap=12)

    # -------------------------------------------------------- infra band
    IY = BY + 116
    p.box(40, IY, 1620, 26, S_BAND, "AI &amp; DATA INFRASTRUCTURE")
    row(p, 40, IY + 30, 1620, 50, [
        (S_NV, "NVIDIA Brev · L40S 48 GB", "instance f8mp81s5j"),
        (S_NV, "NIM containers", "llm :8000 · embed :8001 · rerank :8002"),
        (S_STORE, "Milvus standalone", "v2.5.4 · :19530 · metrics :9091"),
        (S_STORE, "SQLite — system of record", "data/generated/service.sqlite"),
        (S_OPS, "Prometheus :9090 · Grafana :3000", "loopback only"),
    ], pad=0, gap=12)

    # ------------------------------------------------------------ legend
    LY = IY + 92
    p.raw(40, LY, 1620, 54, S_NOTE,
          '<b>Legend&nbsp;&nbsp;</b>'
          '<font style="color:#5C8A1E;">■</font>&nbsp;NVIDIA component &nbsp;&nbsp;'
          '<font style="color:#3A6EA5;">■</font>&nbsp;project Python &nbsp;&nbsp;'
          '<font style="color:#D6B656;">■</font>&nbsp;persistent store &nbsp;&nbsp;'
          '<font style="color:#B85450;">■</font>&nbsp;guardrail / verification '
          '&nbsp;&nbsp;'
          '<font style="color:#7E57C2;">■</font>&nbsp;operations &nbsp;&nbsp;'
          '<font style="color:#9E9E9E;">▨</font>&nbsp;present but not integrated'
          '<br><font style="font-size:10px;">Nothing in the answer path calls '
          'a hosted model. ASR is the one hosted dependency, because there is '
          'no Riva container in this deployment.</font>')

    # fat arrows, drawn last so they sit over the lane fills
    p.raw(LX + LW + 4, Y0 + 180, 36, 40,
          "shape=singleArrow;direction=east;whiteSpace=wrap;html=1;"
          f"fillColor=#EDF6DD;strokeColor={GREEN};strokeWidth=2;", "")
    p.raw(CX + CW + 4, Y0 + 180, 36, 40,
          "shape=singleArrow;direction=east;whiteSpace=wrap;html=1;"
          f"fillColor=#EDF6DD;strokeColor={GREEN};strokeWidth=2;", "")
    return p


# ==========================================================================
# PAGE 2 - the write path
# ==========================================================================
def page_write_path() -> Page:
    p = Page("2 · Write path — an update becomes state", "write", 1560, 1700)

    p.raw(40, 20, 1480, 52, S_TITLE,
          '<b>WRITE PATH</b><font style="font-size:12px;color:#55707E;">'
          '&nbsp;&nbsp;·&nbsp;&nbsp;one spoken or typed update, from the shop '
          'floor to the event log and the vector store '
          '— <i>app/pipeline/run.py</i></font>')

    MX, MW = 440, 340          # main column
    SX, SW = 880, 340          # branches taken off the main line
    QX, QW = 60, 330           # commentary

    start = p.box(MX + 70, 96, 200, 48, S_START, "Shift update")
    d_audio = p.box(MX + 60, 180, 220, 76, S_DEC, "audio, or text?")
    asr = p.box(SX, 180, SW, 76, S_NV,
                "transcribe() — Riva Parakeet CTC 0.6B",
                "gRPC grpc.nvcf.nvidia.com:443 · offline and streaming "
                "both implemented · app/pipeline/asr.py")
    bad = p.box(SX, 282, SW, 54, S_RAIL, "reject",
                "empty transcript, no words, wrong sample rate")

    extract = p.box(MX, 300, MW, 74, S_NV,
                    "extract() — Nemotron Nano 8B",
                    "prose → strict JSON. parse_json() repairs what the "
                    "model returns before any of it is trusted")
    validate = p.box(MX, 404, MW, 68, S_CODE, "validate()",
                     "types, hour ranges, enum membership · "
                     "app/pipeline/extract.py")
    resolve = p.box(MX, 502, MW, 86, S_CODE, "resolve_ro() + resolve_op()",
                    "spoken digits (&quot;oh one four&quot;), shop aliases, "
                    "front/rear position words; op code matched against the "
                    "104-row catalogue, embedding-assisted above threshold 55")

    d_res = p.box(MX + 60, 618, 220, 76, S_DEC, "repair order resolved?")
    clarify = p.box(SX, 618, SW, 92, S_CODE, "clarifying questions",
                    "returned to the speaker. Nothing is written and nothing "
                    "is guessed — a partial resolution still proceeds with "
                    "what did resolve")

    recon = p.box(MX, 738, MW, 68, S_CODE, "reconcile()",
                  "new facts against the current snapshot · "
                  "app/pipeline/reconcile.py")
    d_conf = p.box(MX + 60, 836, 220, 76, S_DEC, "contradicts the snapshot?")
    conflict = p.box(SX, 836, SW, 76, S_RAIL, "surface the contradiction",
                     "shown, never silently clobbered. accept_conflicts=True "
                     "is an explicit operator act, not a default")

    append = p.box(MX, 956, MW, 74, S_STORE, "append to events",
                   "append-only · event_id, ro_number, type, at, actor_id, "
                   "shift, source_update_id, payload")
    fold = p.box(MX, 1060, MW, 74, S_CODE, "fold → RO snapshot",
                 "state is derived from the log, never stored as truth. "
                 "An illegal transition is rejected and reported")
    card = p.box(MX, 1164, MW, 62, S_CODE, "render diff card",
                 "what changed, since when, by whom")
    curate = p.box(MX, 1256, MW, 74, S_NV, "NeMo Curator — quarantine",
                   "InstructionLikeFilter drops notes that address the model "
                   "rather than the record, before they are ever embedded")
    embed = p.box(MX, 1360, MW, 62, S_NV, "embed — nv-embedqa-e5-v5",
                  "1024-dim · NIM :8001")
    upsert = p.box(MX, 1452, MW, 62, S_STORE, "Milvus upsert",
                   "collection &quot;updates&quot; · COSINE · AUTOINDEX")
    done = p.box(MX + 70, 1552, 200, 48, S_END, "searchable")

    for a, b in ((start, d_audio), (asr, extract), (extract, validate),
                 (validate, resolve), (resolve, d_res), (recon, d_conf),
                 (append, fold), (fold, card), (card, curate),
                 (curate, embed), (embed, upsert), (upsert, done)):
        p.edge(a, b)
    p.edge(d_audio, asr, E_MAIN, "audio")
    p.edge(d_audio, extract, E_MAIN, "text")
    p.edge(asr, bad, E_SIDE, "fails")
    p.edge(d_res, clarify, E_SIDE, "no")
    p.edge(d_res, recon, E_MAIN, "yes")
    p.edge(d_conf, conflict, E_SIDE, "yes")
    p.edge(d_conf, append, E_MAIN, "no")

    p.box(QX, 150, QW, 150, S_NOTE, "Two principles",
          "COMPUTE DETERMINISTICALLY, NARRATE WITH THE LLM. The model turns "
          "prose into JSON on the way in and JSON into prose on the way out. "
          "It never counts, never infers state and never does arithmetic.\n\n"
          "UPDATES ARE EVENTS, NOT OVERWRITES. There is a complete audit "
          "trail, and contradictions surface instead of being clobbered.")
    p.box(QX, 326, QW, 112, S_NOTE, "The model is fenced in",
          "Every field a technician can influence is untrusted input. The "
          "extraction is parsed, type-checked and range-checked before any "
          "of it reaches the database, and the free-text fields are carried "
          "as data rather than as instructions.")
    p.box(QX, 1256, QW, 126, S_NOTE, "Why curate a clean corpus",
          "Five of the six stages remove nothing, which is the honest result "
          "for generated data. The sixth earns the pipeline: it removes the "
          "injection vector before indexing, so the retriever can never "
          "surface it. Measured: the known payload caught, zero false "
          "positives across 1,949 notes.")
    return p


# ==========================================================================
# PAGE 3 - the read path
# ==========================================================================
def page_read_path() -> Page:
    p = Page("3 · Read path — a question becomes a cited answer", "read",
             1620, 1580)

    p.raw(40, 20, 1540, 52, S_TITLE,
          '<b>READ PATH</b><font style="font-size:12px;color:#55707E;">'
          '&nbsp;&nbsp;·&nbsp;&nbsp;question → rails → plan → tool → '
          'renderer or narration → verification → cited answer '
          '— <i>app/agent/agent.py</i></font>')

    MX, MW = 480, 380
    LX, LW = 60, 370
    RX, RW = 1000, 380
    h, step = 68, 96
    y = 96

    def main(style, t, s=""):
        nonlocal y
        cid = p.box(MX, y, MW, h, style, t, s)
        y += step
        return cid

    start = p.box(MX + 90, y, 200, 48, S_START, "Question")
    y += 92

    rails_in = main(S_RAIL, "input rails — always on, before any model",
                    "regex: prompt injection, out of scope, unauthorised "
                    "instruction · app/guardrails/rails.py")
    nemo = main(S_NV, "NeMo Guardrails · self check input",
                "a prompt task evaluated by the local nano NIM — one call, "
                "~45 ms. Measured 4/4 adversarial blocked, 24/24 legitimate "
                "allowed")
    refused = p.box(RX, y - step, RW, h, S_RAIL, "refusal",
                    "no tool runs and no model narrates · "
                    "asoia_rail_blocks_total")

    plan = main(S_CODE, "plan_for() — choose the tool",
                "keyword planner by default. The LLM router exists and is "
                "deliberately not paid for: the keyword planner already "
                "routes 24 of 24")
    switch = main(S_OFF, "NeMo Switchyard — off unless ASOIA_SWITCHYARD=on",
                  "route asoia · efficient_first · nano local, "
                  "nemotron-3-super-120b hosted on escalation")
    tool = main(S_CODE, "call one of 10 typed tools",
                "deterministic SQL and vector reads. No subprocess, no eval "
                "of model output, no model-directed sockets")

    d_search = p.box(MX + 80, y, 220, 76, S_DEC, "free-text search?")
    y += 112

    rend = p.box(LX, y, LW, 96, S_CODE, "deterministic renderer",
                 "_ros_summary · _ro_state_summary · _handover_summary · "
                 "_anomaly_summary · _diff_summary · _shift_summary · "
                 "_vehicles_summary — every count, date and booked-hour "
                 "figure is computed in Python from the event log")
    ms = p.box(RX, y, RW, h, S_STORE, "Milvus search",
               "top-k candidates from the &quot;updates&quot; collection")
    rr = p.box(RX, y + 96, RW, h, S_NV, "rerank NIM",
               "nv-rerankqa-mistral-4b-v3 reorders to the passages actually "
               "used")
    narr = p.box(RX, y + 192, RW, h + 12, S_NV, "Nemotron narration",
                 "the one question class a model answers: summarising what "
                 "technicians wrote. A context-only prompt — it is asked for "
                 "prose, never for a figure")
    y += 312

    ground = main(S_RAIL, "check_grounding()",
                  "every digit and decimal in the text must appear in the "
                  "tool payload. Decimals matter most: booked hours are what "
                  "a manager acts on")
    neg = main(S_RAIL, "check_negations()",
               "a flipped &quot;not&quot; inverts the operational meaning of "
               "a safety answer")
    outr = main(S_RAIL, "check_output() — unauthorised-release claim",
                "is &quot;approved for release&quot; supported by the "
                "payload, or invented? This runs in Python because it needs "
                "the payload — a prose rail cannot see it, which is why "
                "there is no self_check_output task")
    ans = main(S_CODE, "answer + citations",
               "[RO-…] [UPD-…] with route, tools used and warnings attached")

    log = p.box(LX, y - step + 2, LW, h, S_STORE, "answer_log · 601 rows",
                "what was asked, what it cited, whether grounding passed, "
                "how long it took")
    met = p.box(RX, y - step + 2, RW, h, S_OPS, "Prometheus + trace span",
                "asoia_answers_total · asoia_answer_seconds · "
                "asoia_tool_calls_total · asoia_grounding_warnings_total")
    end = p.box(MX + 90, y, 200, 48, S_END, "Answer")

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

    p.box(LX, 112, LW, 124, S_NOTE, "The flywheel",
          "Every answer is logged together with the payload it was built "
          "from. scripts/make_eval_dataset.py turns those rows into a "
          "dataset, evals/asoia_byob.py scores it in NeMo Evaluator's own "
          "schema, and the scores gate the next change. The agent's own "
          "output is what measures it.")
    p.box(LX, 254, LW, 110, S_NOTE, "Where the model is not",
          "Five of six question classes never reach an LLM. That is not a "
          "cost saving — it is the reason the figures can be trusted and the "
          "reason the deterministic measures sit at a 100% floor rather than "
          "a hopeful one.")
    return p


# ==========================================================================
# PAGE 4 - the NVIDIA component inventory
# ==========================================================================
# (component, what it does HERE, where it lives, status, style)
COMPONENTS = [
    ("NIM — LLM", "Nemotron Nano 8B. Extraction (prose → JSON) and narration "
     "of search results. Nothing else.",
     "nvcr.io/nim/nvidia/llama-3.1-nemotron-nano-8b-v1 · :8000",
     "running · local", S_NV),
    ("NIM — Embedding", "1024-dim vectors for the 1,949 updates and for "
     "op-code resolution.",
     "nvcr.io/nim/nvidia/nv-embedqa-e5-v5 · :8001", "running · local", S_NV),
    ("NIM — Reranking", "Reorders Milvus candidates to the passages the "
     "answer actually cites.",
     "nvcr.io/nim/nvidia/nv-rerankqa-mistral-4b-v3 · :8002",
     "running · local", S_NV),
    ("Riva — Parakeet ASR", "Speech to text for spoken shift updates. "
     "Offline and streaming paths both implemented.",
     "grpc.nvcf.nvidia.com:443 · app/pipeline/asr.py",
     "running · hosted (no Riva container in this deployment)", S_NV),
    ("NeMo Agent Toolkit", "The agent declared as a NAT workflow: react "
     "agent, one tool group, the same 10 typed tools.",
     "app/agent/workflow.yml · app/agent/nat_functions.py",
     "running · aiq run", S_NV),
    ("NeMo Guardrails", "self check input rail evaluated by the local nano "
     "NIM, over the project's own safety policy.",
     "app/guardrails/config/{config,prompts}.yml · nemo.py",
     "running · ASOIA_NEMO_RAILS=shadow", S_NV),
    ("NeMo Curator", "Six-stage curation. Five find nothing in generated "
     "data; the sixth quarantines the injection vector before indexing.",
     "scripts/curate.py · isolated .venv-curator",
     "running · run/curation/", S_NV),
    ("NeMo Evaluator", "The six measures as BYOB benchmarks, emitted in "
     "Evaluator's own result schema so runs are comparable.",
     "evals/asoia_byob.py · scripts/eval_standard.py",
     "running · response_field, no endpoint needed", S_NV),
    ("NeMo Switchyard", "A loopback routing proxy: nano locally, "
     "nemotron-3-super-120b hosted on escalation.",
     "configs/switchyard.toml · app/routing/switchyard.py",
     "configured · off unless ASOIA_SWITCHYARD=on", S_NV),
    ("Milvus", "The vector store. Standalone, on the box, browsable through "
     "Attu.",
     "milvusdb/milvus:v2.5.4 · :19530 · collection &quot;updates&quot;",
     "running · local", S_STORE),
    ("Observability", "13 metric series scraped into Prometheus and drawn "
     "in Grafana — latency by stage, rail activity, NIM errors.",
     "app/obs/metrics.py · configs/prometheus.yml · "
     "scripts/start_observability.sh", "running · loopback only", S_OPS),
    ("NemoClaw / OpenShell", "Would give a containment boundary and a "
     "sandboxed compute tool. Not reachable: the gateway launchable's sshd "
     "rejects a certificate signed by its own Brev CA.",
     "openshell 0.1.2 in the venv · scripts/openshell_gateway.py",
     "BLOCKED — platform fault, reproduces on a fresh launchable", S_OFF),
]


def page_components() -> Page:
    p = Page("4 · NVIDIA component inventory", "comp", 1620, 1200)
    p.raw(40, 20, 1540, 56, S_TITLE,
          '<b>NVIDIA COMPONENT INVENTORY</b>'
          '<font style="font-size:12px;color:#55707E;">&nbsp;&nbsp;·&nbsp;&nbsp;'
          'eleven built and running, one blocked with evidence — stated that '
          'way deliberately, because it is a stronger position than twelve '
          'claimed</font>')

    cols = [(40, 230), (278, 470), (756, 430), (1194, 386)]
    heads = ["COMPONENT", "WHAT IT DOES HERE", "WHERE IT LIVES", "STATUS"]
    for (x, w), hname in zip(cols, heads):
        p.box(x, 82, w, 26, S_LANE, hname)

    y = 114
    for name, role, where, status, style in COMPONENTS:
        hgt = 76 if len(role) > 95 else 62
        p.box(cols[0][0], y, cols[0][1], hgt,
              style + "verticalAlign=middle;", name)
        p.raw(cols[1][0], y, cols[1][1], hgt,
              style.replace("fontStyle=1;", "") + "verticalAlign=middle;",
              f'<font style="font-size:11px;">{role}</font>')
        p.raw(cols[2][0], y, cols[2][1], hgt,
              S_NOTE + "verticalAlign=middle;fontFamily=Courier New;",
              f'<font style="font-size:10px;">{where}</font>')
        blocked = status.startswith("BLOCKED")
        p.raw(cols[3][0], y, cols[3][1], hgt,
              (S_RAIL if blocked else style) + "verticalAlign=middle;",
              f'<font style="font-size:10.5px;">'
              f'{"<b>" + status + "</b>" if blocked else status}</font>')
        y += hgt + 6

    p.box(40, y + 10, 1540, 92, S_NOTE,
          "What the blocked row actually costs",
          "The containment boundary, and a sandboxed compute tool that would "
          "let derived figures be computed rather than narrated. What it does "
          "not cost: any of the four acceptance criteria, any other row, or "
          "the flywheel — NemoClaw is a boundary around steps, not a step in "
          "the loop. Nothing in the current agent executes untrusted code: "
          "the ten tools are deterministic SQL and vector reads, with no "
          "subprocess, no eval of model output and no model-directed sockets.")
    return p


# ==========================================================================
# PAGE 5 - deployment
# ==========================================================================
def page_deployment() -> Page:
    p = Page("5 · Deployment and ports", "dep", 1520, 1080)
    p.raw(40, 20, 1440, 56, S_TITLE,
          '<b>DEPLOYMENT</b><font style="font-size:12px;color:#55707E;">'
          '&nbsp;&nbsp;·&nbsp;&nbsp;one Brev L40S. All three NIMs co-reside '
          'in roughly 40 GB of the 48 — which is why escalation leaves the '
          'box rather than loading a second local model</font>')

    p.box(40, 82, 1440, 30, S_BAND,
          "NVIDIA Brev · L40S 48 GB · instance f8mp81s5j")

    p.box(60, 130, 1400, 26, S_LANE,
          "GPU — NIM containers (docker, host network published)")
    row(p, 60, 162, 1400, 76, [
        (S_NV, "nim-llm :8000", "llama-3.1-nemotron-nano-8b-v1 · ~22.5 GB · "
         "OpenAI-compatible /v1/chat/completions"),
        (S_NV, "nim-embed :8001", "nv-embedqa-e5-v5 · 1024-dim · /v1/embeddings"),
        (S_NV, "nim-rerank :8002", "nv-rerankqa-mistral-4b-v3 · "
         "/v1/ranking · no hosted equivalent exists"),
    ], pad=0, gap=14)

    p.box(60, 258, 1400, 26, S_LANE, "Stores")
    row(p, 60, 290, 1400, 76, [
        (S_STORE, "asoia-milvus :19530", "milvusdb/milvus:v2.5.4 · "
         "metrics :9091 · collection &quot;updates&quot;"),
        (S_STORE, "SQLite — system of record",
         "data/generated/service.sqlite · WAL · every app read is mode=ro "
         "except the writer"),
        (S_STORE, "data/generated/milvus.db",
         "a Milvus Lite file. Present, NOT in use — the startup report names "
         "it so it cannot be mistaken for the live store again"),
    ], pad=0, gap=14)

    p.box(60, 386, 1400, 26, S_LANE,
          "Application processes (the venv, not containers)")
    row(p, 60, 418, 1400, 72, [
        (S_CODE, "FastAPI :8080", "27 routes · uvicorn · scripts/start_api.sh"),
        (S_CODE, "Gradio :7860", "6 tabs · optional public share link"),
        (S_CODE, "metrics exporter :9400", "/metrics — separate from the API "
         "port, which is why :8080/metrics is a 404"),
    ], pad=0, gap=14)

    p.box(60, 510, 1400, 26, S_LANE,
          "Operator surfaces — bound to 127.0.0.1, reached over one SSH forward")
    row(p, 60, 542, 1400, 72, [
        (S_OPS, "Prometheus :9090", "named volume asoia-prom-data · "
         "retention survives a recreate"),
        (S_OPS, "Grafana :3000", "GF_SERVER_HTTP_ADDR=127.0.0.1"),
        (S_OPS, "Attu :8101", "zilliz/attu:v2.5 — tracks Milvus by minor "
         "version; pointed at Milvus's container IP"),
        (S_OPS, "sqlite-web :8102", "-x -q -f -T · foreign keys on"),
    ], pad=0, gap=14)

    p.box(60, 634, 680, 96, S_NOTE, "One command up, one command down",
          "scripts/stack.sh up — Milvus first, because the API reads the "
          "store; then the NIMs, the API, the UI, the admin UIs and "
          "observability. Every start prints a report naming which store is "
          "actually serving, so the question &quot;which database am I "
          "looking at?&quot; is answered before it is asked.\n\n"
          "scripts/stack.sh down reverses it, including the admin UIs and "
          "the observability stack.")
    p.box(760, 634, 700, 96, S_NOTE, "Why Attu needs the container IP",
          "Milvus sits on docker's default bridge, which has no embedded DNS, "
          "and TCP from a container to the published 19530 on the gateway "
          "address times out on this box. So stores.sh resolves Milvus's "
          "container IP at start and recreates Attu if it has moved. "
          "Diagnosed rather than guessed; the alternative was an Attu that "
          "silently showed an empty store.")

    p.box(60, 804, 1400, 26, S_LANE, "Exposure")
    p.box(60, 836, 1400, 92, S_NOTE, "What is reachable from outside the box",
          "The Gradio share link, when one is published, and nothing else. "
          "8080, 19530, 3000, 9090, 8101 and 8102 are not exposed beyond the "
          "instance; the operator UIs are loopback-bound and reached with "
          "ssh -L. The NVIDIA key lives in .env, is never committed and is "
          "never printed — the stack verifies the line length after every "
          "edit rather than echoing the value.")
    return p


# ==========================================================================
# PAGE 6 - the data model
# ==========================================================================
S_TBL = ("rounded=0;whiteSpace=wrap;html=1;align=left;verticalAlign=top;"
         "spacing=6;fontSize=11;strokeWidth=2;")


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
    p = Page("6 · Data model", "data", 1500, 1040)
    p.raw(40, 20, 1420, 52, S_TITLE,
          '<b>DATA MODEL</b><font style="font-size:12px;color:#55707E;">'
          '&nbsp;&nbsp;·&nbsp;&nbsp;SQLite is the system of record; Milvus '
          'is derived from it and can always be rebuilt. Row counts read '
          'from the running box</font>')

    F_SRC = "fillColor=#FFF4D6;strokeColor=#D6B656;fontColor=#3D3317;"
    F_DER = "fillColor=#EDF6DD;strokeColor=#76B900;fontColor=#1C3307;"
    F_AUD = "fillColor=#EFE9F8;strokeColor=#7E57C2;fontColor=#271A3D;"

    p.box(40, 82, 900, 26, S_LANE,
          "SYSTEM OF RECORD — data/generated/service.sqlite")
    p.box(970, 82, 490, 26, S_LANE, "DERIVED — rebuildable from the log")

    ros = _table(p, 60, 124, 290, "ros", "400 rows",
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
    upd = _table(p, 400, 124, 300, "updates", "1,949 rows",
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

    mil = _table(p, 990, 124, 440, "Milvus collection &quot;updates&quot;",
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
    p = Page("7 · Repair order lifecycle", "life", 2560, 820)
    p.raw(40, 20, 2400, 52, S_TITLE,
          '<b>REPAIR ORDER LIFECYCLE</b>'
          '<font style="font-size:12px;color:#55707E;">&nbsp;&nbsp;·&nbsp;'
          '&nbsp;13 states, and only these transitions. Anything absent is '
          'rejected by the engine and surfaced, never silently applied '
          '— <i>app/state/transitions.py</i></font>')

    S_ST = ("rounded=0;whiteSpace=wrap;html=1;align=center;"
            "verticalAlign=middle;fontSize=11;fontStyle=1;strokeWidth=2;"
            "fillColor=#E8EEF7;strokeColor=#3A6EA5;fontColor=#13293D;")
    S_BL = S_ST.replace("#E8EEF7", "#FFE9C7").replace("#3A6EA5", "#D79B00") \
               .replace("#13293D", "#5A3B00")
    S_TE = S_ST.replace("#E8EEF7", "#E3EEDA").replace("#3A6EA5", "#5C8A1E") \
               .replace("#13293D", "#1C3307")

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
