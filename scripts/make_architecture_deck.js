/**
 * make_architecture_deck.js - the architecture as a seven-slide deck.
 *
 *   node scripts/make_architecture_deck.js [out.pptx]
 *
 * Same source of truth as scripts/make_architecture_diagram.py: constants that
 * sit next to the claim they make. The deck is the diagram's seven sections,
 * one per slide, with the write path and the read path condensed into a single
 * end-to-end application flow - they were always one loop, and splitting them
 * over two pages hid that.
 *
 * Colour carries the argument, as in the diagram: filled green is a served
 * NVIDIA model or NVIDIA infrastructure, outlined green is an NVIDIA framework,
 * plain is this project's own code and the datastores.
 */
const PptxGenJS = require("pptxgenjs");

const THEME = {
  name: "ASOIA",
  headFontFace: "Arial",
  bodyFontFace: "Calibri",
  colors: {
    dk1: "14302A", lt1: "FFFFFF",
    dk2: "1E4035", lt2: "F2F5EF",
    accent1: "76B900", accent2: "5B8C3A", accent3: "C1562A",
    accent4: "AEB7AC", accent5: "3E5A50", accent6: "D9E3D2",
    hlink: "5B8C3A", folHlink: "3E5A50",
  },
};

const INK = "14302A";      // near-black green, backgrounds and bands
const LANE = "1E4035";     // lane headers
const NV = "76B900";       // NVIDIA green, outlines
const NVF = "5B8C3A";      // filled green
const PAPER = "FFFFFF";
const EDGE = "C3CCC0";
const MUTE = "5C6B64";
const WARN = "C1562A";

const W = 13.333, H = 7.5, M = 0.55;
// Nothing on a slide goes below these. The first build had 55 runs under 10pt
// on the architecture slide alone, some at 7.5pt - legible on a laptop at 100%
// and not from the back of a room. Raising the floor is what forced the
// content down to what actually fits.
const NAME_PT = 11, SUB_PT = 10, BOTTOM = H - 0.5;

// ---------------------------------------------------------------- helpers
const txt = (s, o) => Object.assign({ isTextBox: true, margin: 0 }, o);

/** A component box. kind: "nv" filled, "fw" outlined, "std" plain. */
function card(slide, x, y, w, h, kind, name, sub, opts = {}) {
  const fill = kind === "nv" ? NVF : PAPER;
  const line = kind === "nv" ? { color: "446B29", width: 1.5 }
    : kind === "fw" ? { color: NV, width: 1.75 }
    : { color: EDGE, width: 1 };
  slide.addShape("rect", {
    x, y, w, h, fill: { color: fill }, line,
    objectName: opts.objectName || ("card-" + name.slice(0, 18)),
  });
  const nameColor = kind === "nv" ? "FFFFFF" : INK;
  const subColor = kind === "nv" ? "DCE8CF" : MUTE;
  const body = [{ text: name, options: { bold: true, fontSize: opts.ns || NAME_PT, color: nameColor, breakLine: !!sub } }];
  if (sub) body.push({ text: sub, options: { fontSize: opts.ss || SUB_PT, color: subColor } });
  slide.addText(body, txt(null, {
    x: x + 0.07, y: y + 0.04, w: w - 0.14, h: h - 0.08,
    align: "left", valign: sub ? "top" : "middle", lineSpacingMultiple: 0.92,
  }));
}

function band(slide, x, y, w, h, label, opts = {}) {
  slide.addShape("rect", { x, y, w, h, fill: { color: opts.fill || INK }, line: { color: opts.fill || INK } });
  slide.addText(label, txt(null, {
    x: x + 0.12, y, w: w - 0.24, h, align: opts.align || "left", valign: "middle",
    fontSize: opts.fs || 11, bold: true, color: "FFFFFF", charSpacing: 0.6,
  }));
}

function slideTitle(slide, title, sub) {
  slide.addText(title, txt(null, {
    x: M, y: 0.26, w: W - 2 * M, h: 0.44, fontSize: 26, bold: true,
    color: INK, fontFace: "Arial",
  }));
  if (sub) slide.addText(sub, txt(null, {
    x: M, y: 0.74, w: W - 2 * M, h: 0.34, fontSize: 11.5, color: MUTE,
  }));
}

function arrow(slide, x, y, w, h, dir) {
  slide.addShape("rightArrow", {
    x, y, w, h, rotate: dir === "down" ? 90 : 0,
    fill: { color: NV }, line: { color: NV },
  });
}

// ============================================================== 1 · title
function slideTitleCard(pres) {
  const s = pres.addSlide({ sectionTitle: "Overview" });
  s.background = { color: INK };
  s.addText("Automotive Service Operations\nIntelligence Agent", txt(null, {
    x: M, y: 1.38, w: W - 2 * M, h: 1.55, fontSize: 38, bold: true, color: "FFFFFF",
    fontFace: "Arial", lineSpacingMultiple: 0.95,
  }));
  s.addText("Voice and text shift updates become derived repair-order state, a prioritised handover, and a grounded agent — on one L40S", txt(null, {
    x: M, y: 3.05, w: 9.6, h: 0.8, fontSize: 14, color: "C8D6BE",
  }));
  const stats = [
    ["14", "NVIDIA components\n13 running, 1 blocked"],
    ["10", "typed tools\ndeterministic SQL and vector reads"],
    ["100%", "grounded and traceable\n524 of 524 citations resolve"],
    ["5 of 6", "question classes answered\nwith no model call at all"],
  ];
  const sw = (W - 2 * M - 3 * 0.26) / 4;
  stats.forEach(([n, l], i) => {
    const x = M + i * (sw + 0.26);
    s.addShape("rect", { x, y: 4.6, w: sw, h: 1.65, fill: { color: "1E4035" }, line: { color: "2E5245" }, objectName: "stat" + i });
    s.addText(n, txt(null, { x: x + 0.16, y: 4.75, w: sw - 0.3, h: 0.62, fontSize: 30, bold: true, color: NV, fontFace: "Arial" }));
    s.addText(l, txt(null, { x: x + 0.16, y: 5.4, w: sw - 0.3, h: 0.8, fontSize: 11, color: "C8D6BE", lineSpacingMultiple: 0.95 }));
  });
  s.addNotes("One L40S carries all three NIMs. Nothing in the answer path calls a hosted model; speech is the single hosted dependency.");
  return s;
}

// ======================================================= 2 · architecture
// Laid out like the NVIDIA agentic use-case slide this deck is presented
// alongside: the problem and the outcome across the top, then a three-column
// architecture - what arrives on the left, the platform in the middle, what a
// person sees on the right - then governance across the full width, and the
// stack it all runs on along the bottom. The colour argument is unchanged:
// filled green is a served NVIDIA model or NVIDIA infrastructure, outlined
// green is an NVIDIA framework, dashed green is NVIDIA we are not running,
// plain is this project's own code.

/** A legend chip. kind: "nv" filled, "fw" outlined, "off" dashed. */
function chip(s, x, y, w, h, label, kind) {
  const line = kind === "nv" ? { color: "446B29", width: 1.25 }
    : kind === "fw" ? { color: NV, width: 1.5 }
    : { color: NV, width: 1.5, dashType: "dash" };
  s.addShape("rect", {
    x, y, w, h, fill: { color: kind === "nv" ? NVF : PAPER }, line,
    objectName: "legend-" + label.slice(0, 14),
  });
  s.addText(label, txt(null, {
    x, y, w, h, align: "center", valign: "middle", fontSize: 10, bold: true,
    charSpacing: 0.4, color: kind === "nv" ? "FFFFFF" : "4A7023",
  }));
}

/** The objective / outcome panel: a tinted block behind an accent spine. */
function panel(s, x, y, w, h, accent, fill, head, body) {
  s.addShape("rect", { x, y, w, h, fill: { color: fill }, line: { color: fill }, objectName: "panel-" + head });
  s.addShape("rect", { x, y, w: 0.075, h, fill: { color: accent }, line: { color: accent } });
  s.addText(head, txt(null, {
    x: x + 0.22, y: y + 0.06, w: w - 0.42, h: 0.24, fontSize: 11, bold: true,
    color: INK, charSpacing: 0.9, fontFace: "Arial",
  }));
  s.addText(body, txt(null, {
    x: x + 0.22, y: y + 0.31, w: w - 0.42, h: h - 0.38, fontSize: 10.5,
    color: "3E5A50", lineSpacingMultiple: 0.98, valign: "top",
  }));
}

function slideArchitecture(pres) {
  const s = pres.addSlide({ sectionTitle: "Architecture" });

  s.addText("AGENTIC AI USE CASE", txt(null, {
    x: M, y: 0.20, w: 9.0, h: 0.36, fontSize: 23, bold: true, color: INK,
    fontFace: "Arial", charSpacing: 0.5,
  }));
  s.addText("Automotive Service Operations Intelligence Agent", txt(null, {
    x: M, y: 0.56, w: 10.0, h: 0.26, fontSize: 14.5, bold: true, color: "3E5A50", fontFace: "Arial",
  }));

  // ---- the problem, and what the build is for
  const pw = (W - 2 * M - 0.3) / 2;
  panel(s, M, 0.86, pw, 1.14, NV, "EFF4EA", "OBJECTIVE",
    "A service department's day is recorded in speech and free text at the bay. "
    + "Turning that into the state of each repair order is done by hand and from "
    + "memory, so updates are lost and a manager's question gets an answer nobody "
    + "can trace back.");
  const bullet = (t, last) => ({
    text: t, options: { bullet: true, breakLine: !last, fontSize: 10.5, color: "3E5A50" },
  });
  panel(s, M + pw + 0.3, 0.86, pw, 1.14, WARN, "F7EDE6", "BUSINESS OUTCOME", [
    bullet("Spoken and typed updates become repair-order state"),
    bullet("Every figure in an answer traces to an order and an update id"),
    bullet("Five of six question classes need no model call at all", true),
  ]);

  // ---- section heading, and what the colours mean
  s.addText("ARCHITECTURE", txt(null, {
    x: M, y: 2.06, w: 4.0, h: 0.28, fontSize: 14, bold: true, color: INK,
    fontFace: "Arial", charSpacing: 1.2, valign: "middle",
  }));
  const lw = 1.88, lg = 0.1;
  [["NVIDIA COMPONENTS", "nv"], ["NVIDIA FRAMEWORK", "fw"], ["ROADMAP · BLOCKED", "off"]]
    .forEach(([l, k], i) => chip(s, W - M - (3 - i) * (lw + lg) + lg, 2.06, lw, 0.28, l, k));

  const TOP = 2.42;
  const LX = M, LW = 2.42;
  const CX = 3.13, CW = 6.473;
  const RX = 9.763, RW = W - M - 9.763;

  // ---- left and right: one line a card, so the type stays at 11pt
  const sideGroup = (x, w, head, items, y0) => {
    band(s, x, y0, w, 0.22, head, { fill: LANE, fs: 10 });
    items.forEach((it, i) => {
      const [k, n] = Array.isArray(it) ? it : ["std", it];
      card(s, x, y0 + 0.26 + i * 0.42, w, 0.39, k, n, null);
    });
  };
  sideGroup(LX, LW, "INPUTS", ["Spoken update", "Typed update", "Manager question"], TOP);
  sideGroup(LX, LW, "CORPORA", ["Repair orders · 400", "Shift updates · 1,949",
    "Labour op codes · 104", "Staff · 50"], TOP + 1.58);

  // ---- centre: the six lanes, read top to bottom
  band(s, CX, TOP, CW, 0.24, "SERVICE OPERATIONS INTELLIGENCE AGENT", { align: "center", fs: 10.5 });
  const lanes = [
    ["1 · CAPTURE & UNDERSTANDING", [["nv", "Riva ASR"], ["nv", "Nemotron 8B"], ["std", "Entity resolver"], ["std", "Reconciler"]]],
    ["2 · EVENT LOG & DERIVED STATE", [["std", "Event log"], ["std", "Fold engine"], ["std", "Lifecycle gate"], ["std", "Diff card"]]],
    ["3 · PREPARATION & INDEXING", [["fw", "NeMo Curator"], ["nv", "NV-EmbedQA E5"], ["std", "Milvus upsert"], ["std", "Index audit"]]],
    ["4 · RETRIEVAL & GROUNDING", [["std", "Vector search"], ["nv", "NV-RerankQA 4B"], ["std", "Context assembly"], ["std", "Citations"]]],
    ["5 · REASONING & ANSWERING", [["std", "Query planner"], ["fw", "Switchyard"], ["std", "11 typed tools"], ["nv", "Narration"]]],
    ["6 · GUARDRAILS & VERIFICATION", [["fw", "NeMo Guardrails"], ["std", "Injection rail"], ["std", "Grounding rail"], ["std", "Release claim"]]],
  ];
  let y = TOP + 0.28;
  const bw = (CW - 3 * 0.07) / 4;
  lanes.forEach(([hdr, items]) => {
    band(s, CX, y, CW, 0.20, hdr, { fill: LANE, fs: 10 });
    items.forEach(([k, n], i) => {
      const x = CX + i * (bw + 0.07);
      const line = k === "nv" ? { color: "446B29", width: 1.5 }
        : k === "fw" ? { color: NV, width: 1.75 } : { color: EDGE, width: 1 };
      s.addShape("rect", { x, y: y + 0.21, w: bw, h: 0.34, fill: { color: k === "nv" ? NVF : PAPER }, line, objectName: "lane-" + n });
      s.addText(n, txt(null, {
        x: x + 0.05, y: y + 0.21, w: bw - 0.1, h: 0.34, align: "center", valign: "middle",
        fontSize: NAME_PT, bold: true, color: k === "nv" ? "FFFFFF" : INK, lineSpacingMultiple: 0.88,
      }));
    });
    y += 0.55;
  });
  const MIDY = TOP + 1.26;
  arrow(s, LX + LW + 0.02, MIDY, 0.12, 0.16);
  arrow(s, CX + CW + 0.02, MIDY, 0.12, 0.16);

  sideGroup(RX, RW, "EXPERIENCE", ["Operations console · 6 tabs",
    "Review workbench · 7 panes", "HTTP API · 27 routes"], TOP);
  sideGroup(RX, RW, "OBSERVABILITY", [["nv", "NVIDIA DCGM · 19 series"],
    ["std", "Prometheus · 13 series"], ["std", "Grafana · 11 panels"],
    ["std", "Attu and sqlite-web"]], TOP + 1.58);

  // ---- governance, with the one blocked component as its last cell
  const GY = 6.06;
  band(s, M, GY, W - 2 * M, 0.22, "TRACEABILITY, ASSURANCE & GOVERNANCE", { align: "center", fs: 10.5 });
  const gw = (W - 2 * M - 5 * 0.1) / 6;
  const gov = [
    ["std", "Answer log", "706 logged"],
    ["fw", "NeMo Relay", "trace spans"],
    ["fw", "NeMo Evaluator", "run over run"],
    ["nv", "Riva Magpie TTS", "speech harness"],
    ["std", "Acceptance gates", "six floors"],
    ["off", "NemoClaw", "blocked"],
  ];
  gov.forEach(([k, n, sb], i) => {
    const x = M + i * (gw + 0.1), yy = GY + 0.24;
    const blocked = k === "off";
    s.addShape("rect", {
      x, y: yy, w: gw, h: 0.42, fill: { color: k === "nv" ? NVF : PAPER },
      line: blocked ? { color: NV, width: 1.5, dashType: "dash" }
        : k === "fw" ? { color: NV, width: 1.75 } : { color: EDGE, width: 1 },
      objectName: "gov-" + n,
    });
    s.addText([
      { text: n, options: { bold: true, fontSize: 10.5, color: k === "nv" ? "FFFFFF" : (blocked ? "4A7023" : INK), breakLine: true } },
      { text: sb, options: { fontSize: SUB_PT, color: k === "nv" ? "DCE8CF" : MUTE } },
    ], txt(null, { x: x + 0.08, y: yy + 0.03, w: gw - 0.16, h: 0.34, valign: "top", lineSpacingMultiple: 0.86 }));
  });

  // ---- and the stack it runs on
  const IY = 6.76;
  band(s, M, IY, 1.70, 0.24, "Infrastructure", { fs: 10, align: "center", fill: LANE });
  [["NVIDIA Brev · L40S 48 GB", 2.33, 2.40], ["NVIDIA NIM · 3 served models", 4.81, 2.85]]
    .forEach(([l, x, w]) => {
      s.addShape("rect", { x, y: IY, w, h: 0.24, fill: { color: NVF }, line: { color: "446B29" }, objectName: "infra-" + l.slice(0, 12) });
      s.addText(l, txt(null, { x, y: IY, w, h: 0.24, align: "center", valign: "middle", fontSize: 10, bold: true, color: "FFFFFF" }));
    });
  s.addText("Milvus · SQLite · Gradio · FastAPI · Prometheus · Grafana", txt(null, {
    x: 7.76, y: IY, w: W - M - 7.76, h: 0.24, valign: "middle", fontSize: 10, color: MUTE,
  }));

  s.addNotes("Six lanes, read top to bottom. The write path fills lanes 1-3; a question runs through 4-6. Thirteen of the fourteen NVIDIA components are running; NemoClaw is blocked by a platform fault, so it is drawn dashed.");
  return s;
}

// =============================================== 3 · one application flow
function slideFlow(pres) {
  const s = pres.addSlide({ sectionTitle: "Application flow" });
  slideTitle(s, "Application flow",
    "One loop, not two paths: what a technician says becomes the state and the corpus a manager's question is then answered from");

  const FW = W - 2 * M;
  const n = 5, gap = 0.34;                 // the gap is where the arrow goes
  const cw = (FW - (n - 1) * gap) / n;

  // Five steps a row, not six, and plain boxes rather than chevrons. The
  // chevron's point ate a quarter of each box's width, which pushed every
  // caption into three cramped lines and left the direction to be inferred
  // from the shape; an arrow in the gap says it outright.
  function row(yy, h, steps) {
    steps.forEach(([k, name, sub], i) => {
      const x = M + i * (cw + gap);
      const line = k === "nv" ? { color: "446B29", width: 1.5 }
        : k === "fw" ? { color: NV, width: 1.75 } : { color: EDGE, width: 1 };
      s.addShape("rect", {
        x, y: yy, w: cw, h, fill: { color: k === "nv" ? NVF : PAPER }, line,
        objectName: "step-" + name.slice(0, 16),
      });
      s.addText([
        { text: name, options: { bold: true, fontSize: 12, color: k === "nv" ? "FFFFFF" : INK, breakLine: true } },
        { text: sub, options: { fontSize: 10.5, color: k === "nv" ? "DCE8CF" : MUTE } },
      ], txt(null, { x: x + 0.12, y: yy + 0.08, w: cw - 0.24, h: h - 0.14, valign: "top", lineSpacingMultiple: 0.94 }));
      if (i) arrow(s, x - gap + 0.09, yy + h / 2 - 0.08, 0.16, 0.16);
    });
  }

  // ---- what a technician says, becoming the record
  band(s, M, 1.18, FW, 0.26, "CAPTURE  →  STATE   ·   what a technician says, becoming the record", { fs: 10.5 });
  row(1.52, 0.90, [
    ["std", "Capture", "spoken at the bay, or typed"],
    ["nv", "Riva ASR", "speech to text, on the GPU"],
    ["nv", "Nemotron 8B", "free prose → strict JSON"],
    ["std", "Resolve & reconcile", "orders matched; conflicts surfaced"],
    ["fw", "Curate & embed", "six Curator stages, then indexed"],
  ]);

  // ---- the hinge both halves turn on
  s.addShape("downArrow", { x: W / 2 - 0.15, y: 2.50, w: 0.30, h: 0.30, fill: { color: NV }, line: { color: NV } });
  band(s, M, 2.88, FW, 0.26, "SYSTEM OF RECORD   ·   the only thing both halves share", { align: "center", fs: 10.5, fill: LANE });
  const hw = (FW - 0.2) / 2;
  card(s, M, 3.22, hw, 0.60, "std", "Event log — 10,927 events",
    "Append-only. Every order's state is folded from it on each read.", { ns: 12, ss: 10.5 });
  card(s, M + hw + 0.2, 3.22, hw, 0.60, "std", "Vector index — 1,949 @ 1024d",
    "Derived, and rebuildable. Holds no fact the record does not.", { ns: 12, ss: 10.5 });
  s.addShape("downArrow", { x: W / 2 - 0.15, y: 3.90, w: 0.30, h: 0.30, fill: { color: NV }, line: { color: NV } });

  // ---- and what a manager can then ask of it
  band(s, M, 4.28, FW, 0.26, "QUESTION  →  CITED ANSWER   ·   and what a manager can then ask of it", { fs: 10.5 });
  row(4.62, 0.90, [
    ["std", "Question", "console or HTTP API"],
    ["fw", "Rails", "injection, scope, NeMo self-check"],
    ["std", "Plan → tool call", "routes 37 of 37 with no model"],
    ["nv", "Retrieve + rerank", "free-text search only"],
    ["nv", "Compose or narrate", "figures computed, then prose"],
  ]);

  // ---- nothing leaves without passing these
  const vw = (FW - 3 * 0.1) / 4;
  [["Grounding check", "every digit must be in the payload"],
   ["Negation check", "a flipped \"not\" inverts a safety answer"],
   ["Release-claim rail", "authorisation needs evidence"],
   ["Answer log", "route, tools, citations, seconds"],
  ].forEach(([n2, sb], i) => card(s, M + i * (vw + 0.1), 5.66, vw, 0.60, "std", n2, sb, { ns: NAME_PT, ss: SUB_PT }));

  s.addShape("rect", { x: M, y: 6.38, w: FW, h: 0.58, fill: { color: NVF }, line: { color: "446B29" }, objectName: "answer" });
  s.addText([
    { text: "Cited answer   —   ", options: { bold: true, fontSize: 12, color: "FFFFFF" } },
    { text: "every claim tied to a repair order and an update id, and logged — which is what the evaluator scores the next release against", options: { fontSize: 11, color: "DCE8CF" } },
  ], txt(null, { x: M + 0.14, y: 6.38, w: FW - 0.28, h: 0.58, valign: "middle" }));

  s.addNotes("The loop: answers are logged with the payload they were built from, those rows become the evaluation dataset, and the scores gate the next change.");
  return s;
}

// ================================================== 4 · NVIDIA inventory
const COMPONENTS = [
  ["nv", "NIM — LLM", "Prose → JSON in, tool payload → prose out. Nothing else.", "Nemotron Nano 8B · :8000"],
  ["nv", "NIM — Embedding", "Vectors for 1,949 updates and for op-code matching.", "NV-EmbedQA E5 v5 · :8001"],
  ["nv", "NIM — Reranking", "Reorders candidates to the passages actually cited.", "NV-RerankQA 4B · :8002"],
  ["nv", "Riva — ASR", "Speech to text for spoken shift updates.", "Parakeet CTC 0.6B · gRPC"],
  ["nv", "Riva — TTS", "Synthesises the speech the ASR leg is tested with.", "Magpie TTS · gRPC"],
  ["nv", "NVIDIA DCGM", "GPU utilisation, framebuffer, power, temperature.", "19 series · :9401"],
  ["nv", "NVIDIA Brev", "The deployment target carrying all three NIMs.", "L40S 48 GB"],
  ["fw", "NeMo Agent Toolkit", "A second front end onto the same eleven tools; its calls arrive as text.", "tools run 18/18 \u00b7 answers 3/18"],
  ["fw", "NeMo Guardrails", "Input rail judged by the local model.", "self check input"],
  ["fw", "NeMo Curator", "Six stages; the sixth quarantines injection.", "run before indexing"],
  ["fw", "NeMo Evaluator", "Six measures as BYOB benchmarks, run over run.", "Evaluator result schema"],
  ["fw", "NeMo Relay", "How an answer was produced, not just what it said.", "per-stage trace spans"],
  ["fw", "NeMo Switchyard", "Efficient model local, capable one hosted.", "off unless enabled"],
  ["off", "NemoClaw / OpenShell", "Would add a containment boundary and a sandboxed compute tool.", "BLOCKED — platform fault"],
];

function slideComponents(pres) {
  const s = pres.addSlide({ sectionTitle: "Components" });
  slideTitle(s, "NVIDIA components", "Thirteen running, one blocked — every status here measured by running the thing, not by importing it");

  const colW = (W - 2 * M - 0.3) / 2;
  COMPONENTS.forEach(([k, name, role, thing], i) => {
    const col = i < 7 ? 0 : 1, row = i % 7;
    const x = M + col * (colW + 0.3), y = 1.22 + row * 0.80;
    const blocked = k === "off";
    s.addShape("rect", {
      x, y, w: colW, h: 0.70,
      fill: { color: k === "nv" ? NVF : PAPER },
      line: blocked ? { color: NV, width: 1.5, dashType: "dash" }
        : k === "fw" ? { color: NV, width: 1.75 } : { color: EDGE, width: 1 },
      objectName: "comp" + i,
    });
    const nc = k === "nv" ? "FFFFFF" : (blocked ? "4A7023" : INK);
    const sc = k === "nv" ? "DCE8CF" : MUTE;
    s.addText([
      { text: name, options: { bold: true, fontSize: NAME_PT, color: nc, breakLine: true } },
      { text: role, options: { fontSize: SUB_PT, color: sc } },
    ], txt(null, { x: x + 0.12, y: y + 0.05, w: colW - 2.25, h: 0.62, valign: "top", lineSpacingMultiple: 0.92 }));
    s.addText(thing, txt(null, {
      x: x + colW - 2.1, y: y + 0.05, w: 1.98, h: 0.60, align: "right", valign: "middle",
      fontSize: SUB_PT, bold: blocked, color: blocked ? WARN : sc,
    }));
  });

  s.addText("The blocked row costs the containment boundary and a sandboxed compute tool. It is not in the answer path: the agent the console and the API call is this project's own router, and nothing in it executes untrusted code.", txt(null, {
    x: M, y: 6.66, w: W - 2 * M, h: 0.34, fontSize: 10, italic: true, color: MUTE }));
  return s;
}

// ======================================================== 5 · deployment
function slideDeployment(pres) {
  const s = pres.addSlide({ sectionTitle: "Deployment" });
  slideTitle(s, "Deployment", "One Brev L40S. All three NIMs co-reside in roughly 40 GB of the 48 — which is why escalation leaves the box");

  const FW = W - 2 * M;
  band(s, M, 1.22, FW, 0.3, "NVIDIA BREV · L40S 48 GB", { align: "center", fs: 11 });

  const rows = [
    ["GPU — served models", [
      ["nv", "LLM NIM · :8000", "Nemotron Nano 8B · about 22.5 GB"],
      ["nv", "Embedding NIM · :8001", "NV-EmbedQA E5 v5 · 1024 dimensions"],
      ["nv", "Reranking NIM · :8002", "NV-RerankQA 4B · no hosted equivalent"],
      ["nv", "DCGM exporter · :9401", "19 GPU series, scraped every 10s"]]],
    ["Datastores", [
      ["std", "Milvus · :19530", "the vector store; metrics on :9091"],
      ["std", "SQLite", "system of record; every app read is read-only"],
      ["std", "An unused embedded store", "present and NOT in use — the startup report names it"],
      ["std", "Named volumes", "Prometheus retention survives a recreate"]]],
    ["Application and operator surfaces", [
      ["std", "HTTP API · :8080", "27 routes, OpenAPI at /docs"],
      ["std", "Console · :7860", "6 tabs, optional public link"],
      ["std", "Metrics · :9400", "separate from the API port"],
      ["std", "Operator UIs", "Prometheus :9090 · Grafana :3000 · Attu :8101 · sqlite-web :8102 — loopback only"]]],
  ];
  let y = 1.68;
  rows.forEach(([hdr, items]) => {
    band(s, M, y, FW, 0.24, hdr, { fill: LANE, fs: 10.5 });
    const n = items.length, bw = (FW - (n - 1) * 0.1) / n;
    items.forEach(([k, nm, sb], i) => card(s, M + i * (bw + 0.1), y + 0.30, bw, 0.78, k, nm, sb, { ns: NAME_PT, ss: SUB_PT }));
    y += 1.26;
  });

  card(s, M, y + 0.06, FW, 0.78, "std", "What is reachable from outside the box",
    "The optional public console link, and nothing else. The API, the vector store, Grafana, Prometheus and both store browsers are not exposed beyond the instance. The API key lives in an ignored environment file, is never committed and is never printed.",
    { ns: NAME_PT, ss: SUB_PT });
  return s;
}

// ======================================================== 6 · data model
function slideDataModel(pres) {
  const s = pres.addSlide({ sectionTitle: "Data model" });
  slideTitle(s, "Data model", "SQLite is the system of record; the vector store is derived from it and can always be rebuilt");

  const FW = W - 2 * M;
  band(s, M, 1.22, 8.1, 0.26, "SYSTEM OF RECORD", { fill: LANE });
  band(s, M + 8.3, 1.22, FW - 8.3, 0.26, "DERIVED — rebuildable from the log", { fill: LANE });

  function table(x, y, w, h, name, rows, cols, kind) {
    const blocked = false;
    s.addShape("rect", { x, y, w, h, fill: { color: PAPER },
      line: kind === "der" ? { color: NV, width: 1.75 } : { color: EDGE, width: 1 },
      objectName: "tbl-" + name });
    s.addText([
      { text: name, options: { bold: true, fontSize: NAME_PT, color: INK } },
      { text: "   " + rows, options: { fontSize: SUB_PT, color: MUTE } },
    ], txt(null, { x: x + 0.12, y: y + 0.05, w: w - 0.24, h: 0.34 }));
    s.addText(cols.map((c, i) => ({
      text: c, options: { fontSize: SUB_PT, color: MUTE, fontFace: "Courier New", breakLine: i < cols.length - 1 },
    })), txt(null, { x: x + 0.12, y: y + 0.38, w: w - 0.24, h: h - 0.46, valign: "top", lineSpacingMultiple: 0.95 }));
  }

  table(M, 1.6, 2.55, 2.0, "ros", "400", ["ro_number  PK", "vin · registration", "make · model · year", "pay_type · wait_type", "promised_time", "advisor · primary_tech", "concern · category"], "src");
  table(M + 2.75, 1.6, 2.55, 2.0, "updates", "1,949", ["update_id  PK", "ro_number → ros", "staff_id → staff", "at · shift", "text   (untrusted)", "ground_truth"], "src");
  table(M + 5.5, 1.6, 2.6, 2.0, "events", "10,927", ["event_id  PK", "ro_number → ros", "type · at", "actor_id → staff", "shift", "source_update_id", "payload  (json)"], "src");
  table(M, 3.76, 2.55, 1.5, "staff", "50", ["staff_id  PK", "name · role", "skill · shift · team"], "src");
  table(M + 2.75, 3.76, 2.55, 1.5, "labour_ops", "104", ["op_code  PK", "description · category", "flat_rate_hrs", "safety_critical"], "src");
  table(M + 5.5, 3.76, 2.6, 1.5, "answer_log", "706", ["answer_id  PK · at", "question · answer", "route · composed", "grounded · citations"], "src");

  table(M + 8.3, 1.6, FW - 8.3, 2.0, "Milvus collection", "one row per update", ["pk  INT64", "vector  FLOAT_VECTOR(1024)", "update_id · ro_number", "staff · at · shift", "text  VARCHAR(8192)", "vehicle · category · vin"], "der");
  table(M + 8.3, 3.76, FW - 8.3, 1.5, "Repair-order snapshot", "computed, never stored", ["state  (1 of 13)", "blocking · at_risk · safety", "booked hours · tech", "contradictions"], "der");

  card(s, M, 5.46, FW, 0.82, "std", "Why derived means rebuildable",
    "The vector store holds no fact SQLite does not; dropping the collection and re-running the index loses nothing, which is what makes editing it safe to offer at all. The reverse is not true — events can never be rebuilt from anything, which is why they are append-only and why every application read of the record is opened read-only.",
    { ns: NAME_PT, ss: SUB_PT });
  return s;
}

// ========================================================= 7 · lifecycle
// Row 2 reads RIGHT TO LEFT, so every drawn adjacency is a real transition and
// the wrap from AUTHORISED falls straight down onto REPAIR_IN_PROGRESS. The
// states that leave and rejoin the main line are listed rather than drawn: a
// serpentine that puts DECLINED after INVOICED would be a legal-looking edge
// that the engine rejects.
const ROW1 = ["CHECKED_IN", "DISPATCHED", "DIAGNOSING", "ESTIMATE_PREPARED",
              "AWAITING_AUTHORISATION", "AUTHORISED"];
const ROW2 = ["INVOICED", "READY_FOR_DELIVERY", "ROAD_TEST", "QUALITY_CONTROL",
              "REPAIR_IN_PROGRESS"];   // drawn left to right, flowing right to left
const BLOCKING = new Set(["AWAITING_AUTHORISATION", "PARTS_HOLD"]);

function slideLifecycle(pres) {
  const s = pres.addSlide({ sectionTitle: "Lifecycle" });
  slideTitle(s, "Repair order lifecycle", "Thirteen states, and only these transitions. Anything absent is rejected by the engine and surfaced");

  const FW = W - 2 * M;
  const cw = (FW - 5 * 0.22) / 6, ch = 0.8;
  const y1 = 1.46, y2 = 2.76;

  function stateBox(name, x, y, kind) {
    const fill = kind === "end" ? NVF : (kind === "blk" ? "FBEADF" : PAPER);
    const line = kind === "end" ? { color: "446B29", width: 1.5 }
      : kind === "blk" ? { color: WARN, width: 1.75 } : { color: EDGE, width: 1 };
    s.addShape("rect", { x, y, w: cw, h: ch, fill: { color: fill }, line, objectName: "st-" + name });
    const nc = kind === "end" ? "FFFFFF" : (kind === "blk" ? "7A3418" : INK);
    const parts = [{ text: name.replace(/_/g, " "), options: { bold: true, fontSize: 10, color: nc } }];
    if (kind === "blk") parts.push({ text: "\nvehicles sit here", options: { fontSize: SUB_PT, color: WARN } });
    if (kind === "end") parts.push({ text: "\nterminal", options: { fontSize: SUB_PT, color: "DCE8CF" } });
    s.addText(parts, txt(null, { x: x + 0.06, y, w: cw - 0.12, h: ch, align: "center", valign: "middle", lineSpacingMultiple: 0.9 }));
  }

  ROW1.forEach((n, i) => stateBox(n, M + i * (cw + 0.22), y1, BLOCKING.has(n) ? "blk" : "std"));
  ROW2.forEach((n, i) => stateBox(n, M + (i + 1) * (cw + 0.22), y2, n === "INVOICED" ? "end" : "std"));

  // forward arrows: row 1 points right, row 2 points left
  for (let c = 0; c < 5; c++)
    s.addShape("rightArrow", { x: M + c * (cw + 0.22) + cw + 0.03, y: y1 + ch / 2 - 0.07,
      w: 0.16, h: 0.14, fill: { color: NV }, line: { color: NV } });
  for (let c = 1; c < 5; c++)
    s.addShape("leftArrow", { x: M + c * (cw + 0.22) + cw + 0.03, y: y2 + ch / 2 - 0.07,
      w: 0.16, h: 0.14, fill: { color: NV }, line: { color: NV } });
  // the wrap: AUTHORISED straight down onto REPAIR_IN_PROGRESS
  s.addShape("downArrow", { x: M + 5 * (cw + 0.22) + cw / 2 - 0.09, y: y1 + ch + 0.04,
    w: 0.18, h: 0.4, fill: { color: NV }, line: { color: NV } });

  // states that leave and rejoin the line, stated rather than drawn
  band(s, M, 3.80, FW, 0.28, "LEAVES AND REJOINS THE LINE", { fill: LANE, fs: 10.5 });
  const ew = (FW - 0.2) / 2;
  s.addShape("rect", { x: M, y: 4.16, w: ew, h: 0.84, fill: { color: "FBEADF" }, line: { color: WARN, width: 1.75 }, objectName: "st-PARTS_HOLD" });
  s.addText([
    { text: "PARTS HOLD", options: { bold: true, fontSize: NAME_PT, color: "7A3418", breakLine: true } },
    { text: "Entered from diagnosing, authorised or repair-in-progress; leaves to repair-in-progress or back to awaiting authorisation.", options: { fontSize: SUB_PT, color: WARN } },
  ], txt(null, { x: M + 0.12, y: 4.21, w: ew - 0.24, h: 0.76, valign: "top", lineSpacingMultiple: 0.92 }));
  s.addShape("rect", { x: M + ew + 0.2, y: 4.16, w: ew, h: 0.84, fill: { color: PAPER }, line: { color: EDGE, width: 1 }, objectName: "st-DECLINED" });
  s.addText([
    { text: "DECLINED", options: { bold: true, fontSize: NAME_PT, color: INK, breakLine: true } },
    { text: "Entered only from awaiting authorisation, when the customer says no; leaves to ready-for-delivery or straight to invoiced.", options: { fontSize: SUB_PT, color: MUTE } },
  ], txt(null, { x: M + ew + 0.32, y: 4.21, w: ew - 0.24, h: 0.76, valign: "top", lineSpacingMultiple: 0.92 }));

  const nw = (FW - 2 * 0.2) / 3;
  [["Deliberately not IN_PROGRESS / COMPLETE",
    "The states that matter are the blocking ones — that is where vehicles actually sit, and where the agent creates value."],
   ["The authorisation rule",
    "Repair cannot legitimately begin before the customer has said yes. That gate is why the release-claim rail exists."],
   ["QC failure is an edge, not an error path",
    "Quality control and road test can both send a job back to the bench, and supplementary work re-opens authorisation."],
  ].forEach(([n2, sb], i) => card(s, M + i * (nw + 0.2), 5.14, nw, 1.30, "std", n2, sb, { ns: NAME_PT, ss: SUB_PT }));

  s.addText("Amber marks the two blocking states; green marks the terminal one. The second row flows right to left, so every arrow drawn here is a transition the engine actually allows.", txt(null, {
    x: M, y: 6.56, w: FW, h: 0.34, fontSize: 10, italic: true, color: MUTE }));
  return s;
}

// ================================================================= build
async function main() {
  const out = process.argv[2] || "docs/architecture-deck.pptx";
  const pres = new PptxGenJS();
  pres.layout = "LAYOUT_WIDE";
  pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
  pres.author = "Automotive Service Operations Intelligence Agent";
  pres.title = "Automotive Service Operations Intelligence Agent";

  ["Overview", "Architecture", "Application flow", "Components", "Deployment",
   "Data model", "Lifecycle"].forEach((t) => pres.addSection({ title: t }));

  slideTitleCard(pres);
  slideArchitecture(pres);
  slideFlow(pres);
  slideComponents(pres);
  slideDeployment(pres);
  slideDataModel(pres);
  slideLifecycle(pres);

  await pres.writeFile({ fileName: out });
  console.log("wrote " + out + "  (7 slides)");
}
main().catch((e) => { console.error(e); process.exit(1); });
