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
function slideArchitecture(pres) {
  const s = pres.addSlide({ sectionTitle: "Architecture" });
  slideTitle(s, "Architecture", "Green is NVIDIA: filled is a served model or infrastructure, outlined is a framework, plain is this project's own code");

  const TOP = 1.16;
  const LX = M, LW = 2.25;
  const CX = 3.05, CW = 6.95;
  const RX = 10.30, RW = W - M - 10.30;

  band(s, CX, TOP, CW, 0.28, "SERVICE OPERATIONS INTELLIGENCE PLATFORM", { align: "center" });

  // ---- left: one line per card, so the type stays at 11pt
  band(s, LX, TOP, LW, 0.28, "Inputs", { fill: LANE });
  ["Spoken update", "Typed update", "Manager question"].forEach((n, i) =>
    card(s, LX, TOP + 0.36 + i * 0.54, LW, 0.46, "std", n, null));
  band(s, LX, TOP + 2.02, LW, 0.28, "Corpora", { fill: LANE });
  ["Repair orders · 400", "Shift updates · 1,949", "Labour operations · 104",
   "Staff · 50"].forEach((n, i) =>
    card(s, LX, TOP + 2.38 + i * 0.51, LW, 0.44, "std", n, null));

  // ---- centre
  const lanes = [
    ["1 · CAPTURE & UNDERSTANDING", [["nv", "Riva ASR"], ["nv", "Nemotron 8B"], ["std", "Entity resolver"], ["std", "Reconciler"]]],
    ["2 · EVENT LOG & DERIVED STATE", [["std", "Event log"], ["std", "Fold engine"], ["std", "Lifecycle gate"], ["std", "Diff card"]]],
    ["3 · PREPARATION & INDEXING", [["fw", "NeMo Curator"], ["nv", "NV-EmbedQA E5"], ["std", "Milvus upsert"], ["std", "Index audit"]]],
    ["4 · RETRIEVAL & GROUNDING", [["std", "Vector search"], ["nv", "NV-RerankQA 4B"], ["std", "Context assembly"], ["std", "Citations"]]],
    ["5 · REASONING & ANSWERING", [["std", "Query planner"], ["fw", "Switchyard"], ["std", "10 typed tools"], ["nv", "Narration"]]],
    ["6 · GUARDRAILS & VERIFICATION", [["fw", "NeMo Guardrails"], ["std", "Injection rail"], ["std", "Grounding rail"], ["std", "Release claim"]]],
  ];
  let y = TOP + 0.36;
  const bw = (CW - 3 * 0.08) / 4;
  lanes.forEach(([hdr, items]) => {
    band(s, CX, y, CW, 0.24, hdr, { fill: LANE, fs: 10 });
    items.forEach(([k, n], i) => {
      const x = CX + i * (bw + 0.08);
      const fill = k === "nv" ? NVF : PAPER;
      const line = k === "nv" ? { color: "446B29", width: 1.5 }
        : k === "fw" ? { color: NV, width: 1.75 } : { color: EDGE, width: 1 };
      s.addShape("rect", { x, y: y + 0.28, w: bw, h: 0.44, fill: { color: fill }, line, objectName: "lane-" + n });
      s.addText(n, txt(null, { x: x + 0.06, y: y + 0.28, w: bw - 0.12, h: 0.44,
        align: "center", valign: "middle", fontSize: NAME_PT, bold: true,
        color: k === "nv" ? "FFFFFF" : INK, lineSpacingMultiple: 0.88 }));
    });
    y += 0.74;
  });

  // ---- right
  band(s, RX, TOP, RW, 0.28, "Experience", { fill: LANE });
  ["Operations console · 6 tabs", "Review workbench · 7 panes",
   "HTTP API · 27 routes"].forEach((n, i) =>
    card(s, RX, TOP + 0.36 + i * 0.54, RW, 0.46, "std", n, null));
  band(s, RX, TOP + 2.02, RW, 0.28, "Observability", { fill: LANE });
  [["nv", "NVIDIA DCGM · 19 GPU series"], ["std", "Prometheus · 13 app series"],
   ["std", "Grafana · 11 panels"], ["std", "Attu and sqlite-web"]].forEach(([k, n], i) =>
    card(s, RX, TOP + 2.38 + i * 0.51, RW, 0.44, k, n, null));

  // ---- governance, with the blocked component as its last cell
  const GY = 6.06;
  band(s, M, GY, W - 2 * M, 0.28, "TRACEABILITY, ASSURANCE & GOVERNANCE", { align: "center" });
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
    const x = M + i * (gw + 0.1), yy = GY + 0.36;
    const blocked = k === "off";
    s.addShape("rect", { x, y: yy, w: gw, h: 0.52,
      fill: { color: k === "nv" ? NVF : PAPER },
      line: blocked ? { color: NV, width: 1.5, dashType: "dash" }
        : k === "fw" ? { color: NV, width: 1.75 } : { color: EDGE, width: 1 },
      objectName: "gov-" + n });
    s.addText([
      { text: n, options: { bold: true, fontSize: 10.5, color: k === "nv" ? "FFFFFF" : (blocked ? "4A7023" : INK), breakLine: true } },
      { text: sb, options: { fontSize: SUB_PT, color: k === "nv" ? "DCE8CF" : MUTE } },
    ], txt(null, { x: x + 0.08, y: yy + 0.03, w: gw - 0.16, h: 0.46, valign: "top", lineSpacingMultiple: 0.9 }));
  });

  s.addNotes("Six lanes, read top to bottom. The write path fills lanes 1-3; a question runs through 4-6. NemoClaw is the one NVIDIA component of fourteen not running.");
  return s;
}

// =============================================== 3 · one application flow
function slideFlow(pres) {
  const s = pres.addSlide({ sectionTitle: "Application flow" });
  slideTitle(s, "Application flow",
    "One loop, not two paths: what a technician says becomes the state and the corpus a manager's question is then answered from");

  const FW = W - 2 * M;
  const n = 6, gap = 0.1;
  const cw = (FW - (n - 1) * gap) / n;

  function chevrons(y, steps) {
    steps.forEach(([k, name, sub], i) => {
      const x = M + i * (cw + gap);
      const fill = k === "nv" ? NVF : (k === "fw" ? PAPER : PAPER);
      const line = k === "nv" ? { color: "446B29", width: 1.5 }
        : k === "fw" ? { color: NV, width: 1.75 } : { color: EDGE, width: 1 };
      s.addShape(i === 0 ? "rect" : "chevron", {
        x, y, w: cw, h: 0.92, fill: { color: fill }, line,
        objectName: "step-" + name.slice(0, 16),
      });
      const nc = k === "nv" ? "FFFFFF" : INK;
      const sc = k === "nv" ? "DCE8CF" : MUTE;
      s.addText([
        { text: name, options: { bold: true, fontSize: 10.5, color: nc, breakLine: true } },
        { text: sub, options: { fontSize: SUB_PT, color: sc } },
      ], txt(null, {
        x: x + (i === 0 ? 0.1 : 0.24), y: y + 0.07, w: cw - (i === 0 ? 0.2 : 0.38), h: 0.78,
        valign: "top", lineSpacingMultiple: 0.9,
      }));
    });
  }

  // ---- write half
  band(s, M, 1.16, FW, 0.26, "CAPTURE  →  STATE   ·   what a technician says, becoming the record", { fs: 10.5 });
  chevrons(1.48, [
    ["std", "Capture", "spoken or typed"],
    ["nv", "Riva ASR", "speech to text"],
    ["nv", "Nemotron 8B", "prose → strict JSON"],
    ["std", "Resolve", "orders, op codes, spoken digits"],
    ["std", "Reconcile", "conflicts surfaced, not clobbered"],
    ["fw", "Curate and embed", "quarantine, then index"],
  ]);

  // ---- the hinge
  s.addShape("downArrow", { x: 6.47, y: 2.50, w: 0.42, h: 0.26, fill: { color: NV }, line: { color: NV } });
  band(s, M, 2.82, FW, 0.26, "SYSTEM OF RECORD   ·   the only thing both halves share", { align: "center", fs: 10.5, fill: LANE });
  const hw = (FW - 0.2) / 2;
  card(s, M, 3.14, hw, 0.60, "std", "Event log — 10,927 events",
    "Append-only. Every repair order's state is folded from it on each read.", { ns: NAME_PT, ss: SUB_PT });
  card(s, M + hw + 0.2, 3.14, hw, 0.60, "std", "Vector index — 1,949 @ 1024d",
    "Derived, and rebuildable. Holds no fact the record does not.", { ns: NAME_PT, ss: SUB_PT });
  s.addShape("downArrow", { x: 6.47, y: 3.78, w: 0.42, h: 0.26, fill: { color: NV }, line: { color: NV } });

  // ---- read half
  band(s, M, 4.02, FW, 0.26, "QUESTION  →  CITED ANSWER   ·   and what a manager can then ask of it", { fs: 10.5 });
  chevrons(4.34, [
    ["std", "Question", "console or HTTP API"],
    ["fw", "Rails", "injection, scope, NeMo self-check"],
    ["std", "Plan", "routes 24 of 24 with no model"],
    ["std", "Tool call", "one of ten, deterministic"],
    ["nv", "Retrieve + rerank", "free-text search only"],
    ["nv", "Compose or narrate", "figures computed, prose written"],
  ]);

  // ---- verification + answer
  const vw = (FW - 3 * 0.1) / 4;
  [["Grounding check", "every digit must be in the payload"],
   ["Negation check", "a flipped \"not\" inverts a safety answer"],
   ["Release-claim rail", "authorisation needs evidence"],
   ["Answer log", "route, tools, citations, seconds"],
  ].forEach(([n2, sb], i) => card(s, M + i * (vw + 0.1), 5.40, vw, 0.62, "std", n2, sb, { ns: NAME_PT, ss: SUB_PT }));

  s.addShape("rect", { x: M, y: 6.14, w: FW, h: 0.54, fill: { color: NVF }, line: { color: "446B29" }, objectName: "answer" });
  s.addText([
    { text: "Cited answer   —   ", options: { bold: true, fontSize: 11.5, color: "FFFFFF" } },
    { text: "every claim tied to a repair order and an update id, and logged — which is what the evaluator scores the next release against", options: { fontSize: 11, color: "DCE8CF" } },
  ], txt(null, { x: M + 0.14, y: 6.14, w: FW - 0.28, h: 0.54, valign: "middle" }));

  s.addText("Five of six question classes never reach a model — that is why the deterministic measures sit at a 100% floor rather than a hopeful one", txt(null, {
    x: M, y: 6.70, w: FW, h: 0.3, fontSize: 10, italic: true, color: MUTE }));
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
  ["fw", "NeMo Agent Toolkit", "A second front end onto the same ten tools.", "6 of 6 question classes"],
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
