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

const W = 13.333, H = 7.5, M = 0.5;

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
  const body = [{ text: name, options: { bold: true, fontSize: opts.ns || 11, color: nameColor, breakLine: !!sub } }];
  if (sub) body.push({ text: sub, options: { fontSize: opts.ss || 8.5, color: subColor } });
  slide.addText(body, txt(null, {
    x: x + 0.07, y: y + 0.04, w: w - 0.14, h: h - 0.08,
    align: "left", valign: sub ? "top" : "middle", lineSpacingMultiple: 0.92,
  }));
}

function band(slide, x, y, w, h, label, opts = {}) {
  slide.addShape("rect", { x, y, w, h, fill: { color: opts.fill || INK }, line: { color: opts.fill || INK } });
  slide.addText(label, txt(null, {
    x: x + 0.12, y, w: w - 0.24, h, align: opts.align || "left", valign: "middle",
    fontSize: opts.fs || 10.5, bold: true, color: "FFFFFF", charSpacing: 0.6,
  }));
}

function slideTitle(slide, title, sub) {
  slide.addText(title, txt(null, {
    x: M, y: 0.28, w: W - 2 * M, h: 0.42, fontSize: 26, bold: true,
    color: INK, fontFace: "Arial",
  }));
  if (sub) slide.addText(sub, txt(null, {
    x: M, y: 0.72, w: W - 2 * M, h: 0.42, fontSize: 11, color: MUTE,
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
    s.addText(l, txt(null, { x: x + 0.16, y: 5.4, w: sw - 0.3, h: 0.75, fontSize: 9.5, color: "C8D6BE", lineSpacingMultiple: 0.95 }));
  });
  s.addNotes("One L40S carries all three NIMs. Nothing in the answer path calls a hosted model; speech is the single hosted dependency.");
  return s;
}

// ======================================================= 2 · architecture
function slideArchitecture(pres) {
  const s = pres.addSlide({ sectionTitle: "Architecture" });
  slideTitle(s, "Architecture", "Green is NVIDIA: filled is a served model or infrastructure, outlined is a framework, plain is this project's own code");

  const top = 1.20;
  const LX = M, LW = 2.15;
  const CX = 2.95, CW = 7.45;
  const RX = 10.62, RW = W - M - 10.62;

  band(s, CX, top, CW, 0.26, "SERVICE OPERATIONS INTELLIGENCE PLATFORM", { align: "center" });

  // left
  band(s, LX, top, LW, 0.26, "Inputs", { fill: LANE });
  [["Spoken update", "dictated at the bay"], ["Typed update", "same pipeline"],
   ["Manager question", "console or API"]].forEach(([n, sb], i) =>
    card(s, LX, top + 0.34 + i * 0.6, LW, 0.52, "std", n, sb, { ns: 10, ss: 8 }));
  band(s, LX, top + 2.2, LW, 0.26, "Corpora", { fill: LANE });
  [["Repair orders", "400"], ["Shift updates", "1,949"],
   ["Labour operations", "104"], ["Staff", "50"]].forEach(([n, sb], i) =>
    card(s, LX, top + 2.54 + i * 0.50, LW, 0.44, "std", n, sb, { ns: 10, ss: 8 }));

  // centre lanes
  const lanes = [
    ["1 · CAPTURE & UNDERSTANDING", [["nv", "Riva Parakeet ASR"], ["nv", "Nemotron Nano 8B"], ["std", "Entity resolver"], ["std", "Reconciler"]]],
    ["2 · EVENT LOG & DERIVED STATE", [["std", "Event log · 10,927"], ["std", "Fold engine"], ["std", "Lifecycle gate · 13"], ["std", "Diff card"]]],
    ["3 · PREPARATION & INDEXING", [["fw", "NeMo Curator"], ["nv", "NV-EmbedQA E5 v5"], ["std", "Milvus upsert"], ["std", "Index audit"]]],
    ["4 · RETRIEVAL & GROUNDING", [["std", "Vector search"], ["nv", "NV-RerankQA 4B"], ["std", "Context assembly"], ["std", "Citation set"]]],
    ["5 · REASONING & ANSWERING", [["std", "Query planner"], ["fw", "NeMo Switchyard"], ["std", "10 typed tools"], ["nv", "Nemotron narration"]]],
    ["6 · GUARDRAILS & VERIFICATION", [["fw", "NeMo Guardrails"], ["std", "Injection rail"], ["std", "Grounding rail"], ["std", "Release-claim rail"]]],
  ];
  // 0.70 per lane: six of them have to clear the governance band at 5.80.
  let y = top + 0.34;
  const bw = (CW - 3 * 0.08) / 4;
  lanes.forEach(([hdr, items]) => {
    band(s, CX, y, CW, 0.20, hdr, { fill: LANE, fs: 8.5 });
    items.forEach(([k, n], i) => card(s, CX + i * (bw + 0.08), y + 0.24, bw, 0.40, k, n, null, { ns: 9.5 }));
    y += 0.70;
  });

  // right
  band(s, RX, top, RW, 0.26, "Experience", { fill: LANE });
  [["Operations console", "6 tabs"], ["Review workbench", "7 panes"],
   ["HTTP API", "27 routes"]].forEach(([n, sb], i) =>
    card(s, RX, top + 0.34 + i * 0.6, RW, 0.52, "std", n, sb, { ns: 10, ss: 8 }));
  band(s, RX, top + 2.2, RW, 0.26, "Observability", { fill: LANE });
  [["nv", "NVIDIA DCGM", "19 GPU series"], ["std", "Prometheus", "13 app series"],
   ["std", "Grafana", "11 panels"], ["std", "Store browsers", "Attu, sqlite-web"]].forEach(([k, n, sb], i) =>
    card(s, RX, top + 2.54 + i * 0.50, RW, 0.44, k, n, sb, { ns: 10, ss: 8 }));

  band(s, M, 5.84, W - 2 * M, 0.26, "TRACEABILITY, ASSURANCE & GOVERNANCE", { align: "center" });
  const gw = (W - 2 * M - 4 * 0.1) / 5;
  [["std", "Answer log", "706 answers, what each cited"],
   ["fw", "NeMo Relay", "per-stage trace spans"],
   ["fw", "NeMo Evaluator", "six measures, run over run"],
   ["nv", "Riva Magpie TTS", "the spoken-update test harness"],
   ["std", "Acceptance gates", "routing 90 · grounding 100 · refusal 100"],
  ].forEach(([k, n, sb], i) => card(s, M + i * (gw + 0.1), 6.18, gw, 0.56, k, n, sb, { ns: 9.5, ss: 7.5 }));

  s.addText("NemoClaw / OpenShell — the sandbox gateway — is blocked by a platform fault and is the one NVIDIA component of fourteen not running", txt(null, {
    x: M, y: 6.84, w: W - 2 * M, h: 0.3, fontSize: 9, italic: true, color: MUTE }));
  s.addNotes("Six lanes, read top to bottom. The write path fills lanes 1-3; a question runs through 4-6.");
  return s;
}

// =============================================== 3 · one application flow
function slideFlow(pres) {
  const s = pres.addSlide({ sectionTitle: "Application flow" });
  slideTitle(s, "Application flow",
    "One loop, not two paths: what a technician says becomes the state and the corpus a manager's question is then answered from");

  const FW = W - 2 * M;
  const n = 7, gap = 0.06;
  const cw = (FW - (n - 1) * gap) / n;

  function chevrons(y, steps) {
    steps.forEach(([k, name, sub], i) => {
      const x = M + i * (cw + gap);
      const fill = k === "nv" ? NVF : (k === "fw" ? PAPER : PAPER);
      const line = k === "nv" ? { color: "446B29", width: 1.5 }
        : k === "fw" ? { color: NV, width: 1.75 } : { color: EDGE, width: 1 };
      s.addShape(i === 0 ? "rect" : "chevron", {
        x, y, w: cw, h: 0.82, fill: { color: fill }, line,
        objectName: "step-" + name.slice(0, 16),
      });
      const nc = k === "nv" ? "FFFFFF" : INK;
      const sc = k === "nv" ? "DCE8CF" : MUTE;
      s.addText([
        { text: name, options: { bold: true, fontSize: 9.5, color: nc, breakLine: true } },
        { text: sub, options: { fontSize: 7.5, color: sc } },
      ], txt(null, {
        x: x + (i === 0 ? 0.08 : 0.2), y: y + 0.06, w: cw - (i === 0 ? 0.16 : 0.3), h: 0.7,
        valign: "top", lineSpacingMultiple: 0.9,
      }));
    });
  }

  // ---- write half
  band(s, M, 1.18, FW, 0.24, "CAPTURE  →  STATE   ·   what a technician says, becoming the record", { fs: 9.5 });
  chevrons(1.5, [
    ["std", "Capture", "spoken or typed, one entry point"],
    ["nv", "Riva Parakeet ASR", "speech to text, streaming or offline"],
    ["nv", "Nemotron Nano 8B", "prose → strict JSON"],
    ["std", "Resolve", "repair orders, op codes, spoken digits"],
    ["std", "Reconcile", "new facts vs the snapshot; conflicts surfaced"],
    ["std", "Append + fold", "append-only log; state derived on read"],
    ["fw", "Curate + embed", "injection quarantined, then 1024-dim vectors"],
  ]);

  // ---- the hinge
  s.addShape("downArrow", { x: 6.45, y: 2.42, w: 0.42, h: 0.26, fill: { color: NV }, line: { color: NV } });
  band(s, M, 2.74, FW, 0.24, "SYSTEM OF RECORD   ·   the only thing both halves share", { align: "center", fs: 9.5, fill: LANE });
  const hw = (FW - 0.2) / 2;
  card(s, M, 3.06, hw, 0.62, "std", "Event log — 10,927 events",
    "Append-only. Every repair order's state is folded from it on each read, never stored.", { ns: 10.5, ss: 8.5 });
  card(s, M + hw + 0.2, 3.06, hw, 0.62, "std", "Vector index — 1,949 passages @ 1024d",
    "Derived, and rebuildable from the log. Holds no fact the record does not.", { ns: 10.5, ss: 8.5 });
  s.addShape("downArrow", { x: 6.45, y: 3.76, w: 0.42, h: 0.26, fill: { color: NV }, line: { color: NV } });

  // ---- read half
  band(s, M, 4.08, FW, 0.24, "QUESTION  →  CITED ANSWER   ·   and what a manager can then ask of it", { fs: 9.5 });
  chevrons(4.4, [
    ["std", "Question", "console or HTTP API"],
    ["fw", "Rails", "injection, scope and NeMo self-check, before any model"],
    ["std", "Plan", "keyword planner routes 24 of 24"],
    ["std", "Tool call", "one of ten; deterministic reads"],
    ["nv", "Retrieve + rerank", "only for free-text search"],
    ["std", "Compose", "every figure computed in Python"],
    ["nv", "Narrate", "prose only, from the tool payload"],
  ]);

  // ---- verification + answer
  const vw = (FW - 3 * 0.1) / 4;
  [["Grounding check", "every digit must appear in the payload"],
   ["Negation check", "a flipped \"not\" inverts a safety answer"],
   ["Release-claim rail", "authorisation needs evidence, not phrasing"],
   ["Answer log", "question, route, tools, citations, seconds"],
  ].forEach(([n2, sb], i) => card(s, M + i * (vw + 0.1), 5.34, vw, 0.5, "std", n2, sb, { ns: 9, ss: 7.5 }));

  s.addShape("rect", { x: M, y: 5.98, w: FW, h: 0.52, fill: { color: NVF }, line: { color: "446B29" }, objectName: "answer" });
  s.addText([
    { text: "Cited answer   —   ", options: { bold: true, fontSize: 11.5, color: "FFFFFF" } },
    { text: "every claim tied to a repair order and an update id — and logged, which is what the evaluator scores the next release against", options: { fontSize: 9.5, color: "DCE8CF" } },
  ], txt(null, { x: M + 0.14, y: 5.98, w: FW - 0.28, h: 0.52, valign: "middle" }));

  s.addText("Five of six question classes never reach a model — that is why the deterministic measures sit at a 100% floor rather than a hopeful one", txt(null, {
    x: M, y: 6.62, w: FW, h: 0.26, fontSize: 9, italic: true, color: MUTE }));
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
    const x = M + col * (colW + 0.3), y = 1.2 + row * 0.79;
    const blocked = k === "off";
    s.addShape("rect", {
      x, y, w: colW, h: 0.68,
      fill: { color: k === "nv" ? NVF : PAPER },
      line: blocked ? { color: NV, width: 1.5, dashType: "dash" }
        : k === "fw" ? { color: NV, width: 1.75 } : { color: EDGE, width: 1 },
      objectName: "comp" + i,
    });
    const nc = k === "nv" ? "FFFFFF" : (blocked ? "4A7023" : INK);
    const sc = k === "nv" ? "DCE8CF" : MUTE;
    s.addText([
      { text: name, options: { bold: true, fontSize: 10.5, color: nc, breakLine: true } },
      { text: role, options: { fontSize: 8.5, color: sc } },
    ], txt(null, { x: x + 0.12, y: y + 0.05, w: colW - 2.35, h: 0.6, valign: "top", lineSpacingMultiple: 0.92 }));
    s.addText(thing, txt(null, {
      x: x + colW - 2.2, y: y + 0.05, w: 2.08, h: 0.58, align: "right", valign: "middle",
      fontSize: 8.5, bold: blocked, color: blocked ? WARN : sc,
    }));
  });

  s.addText("The blocked row costs the containment boundary, and a sandboxed compute tool that would let derived figures be computed rather than narrated. It is not in the answer path: the agent the console and the API call is this project's own router, and nothing in it executes untrusted code.", txt(null, {
    x: M, y: 6.82, w: W - 2 * M, h: 0.36, fontSize: 9, italic: true, color: MUTE }));
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
    band(s, M, y, FW, 0.24, hdr, { fill: LANE, fs: 9.5 });
    const n = items.length, bw = (FW - (n - 1) * 0.1) / n;
    items.forEach(([k, nm, sb], i) => card(s, M + i * (bw + 0.1), y + 0.28, bw, 0.72, k, nm, sb, { ns: 9.5, ss: 8 }));
    y += 1.22;
  });

  card(s, M, y + 0.06, FW, 0.78, "std", "What is reachable from outside the box",
    "The optional public console link, and nothing else. The API, the vector store, Grafana, Prometheus and both store browsers are not exposed beyond the instance. The API key lives in an ignored environment file, is never committed and is never printed.",
    { ns: 10.5, ss: 9 });
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
      { text: name, options: { bold: true, fontSize: 10.5, color: INK } },
      { text: "   " + rows, options: { fontSize: 9, color: MUTE } },
    ], txt(null, { x: x + 0.12, y: y + 0.05, w: w - 0.24, h: 0.34 }));
    s.addText(cols.map((c, i) => ({
      text: c, options: { fontSize: 8.5, color: MUTE, fontFace: "Courier New", breakLine: i < cols.length - 1 },
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
    { ns: 10.5, ss: 9 });
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
    if (kind === "blk") parts.push({ text: "\nvehicles sit here", options: { fontSize: 8, color: WARN } });
    if (kind === "end") parts.push({ text: "\nterminal", options: { fontSize: 8, color: "DCE8CF" } });
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
  band(s, M, 3.86, FW, 0.26, "LEAVES AND REJOINS THE LINE", { fill: LANE, fs: 9.5 });
  const ew = (FW - 0.2) / 2;
  s.addShape("rect", { x: M, y: 4.2, w: ew, h: 0.72, fill: { color: "FBEADF" }, line: { color: WARN, width: 1.75 }, objectName: "st-PARTS_HOLD" });
  s.addText([
    { text: "PARTS HOLD", options: { bold: true, fontSize: 10.5, color: "7A3418", breakLine: true } },
    { text: "Entered from diagnosing, authorised or repair-in-progress; leaves to repair-in-progress or back to awaiting authorisation. One of the two states where vehicles actually sit.", options: { fontSize: 8.5, color: WARN } },
  ], txt(null, { x: M + 0.12, y: 4.25, w: ew - 0.24, h: 0.62, valign: "top", lineSpacingMultiple: 0.92 }));
  s.addShape("rect", { x: M + ew + 0.2, y: 4.2, w: ew, h: 0.72, fill: { color: PAPER }, line: { color: EDGE, width: 1 }, objectName: "st-DECLINED" });
  s.addText([
    { text: "DECLINED", options: { bold: true, fontSize: 10.5, color: INK, breakLine: true } },
    { text: "Entered only from awaiting authorisation, when the customer says no; leaves to ready-for-delivery or straight to invoiced. The work does not happen, and the vehicle still has to go back.", options: { fontSize: 8.5, color: MUTE } },
  ], txt(null, { x: M + ew + 0.32, y: 4.25, w: ew - 0.24, h: 0.62, valign: "top", lineSpacingMultiple: 0.92 }));

  const nw = (FW - 2 * 0.2) / 3;
  [["Deliberately not IN_PROGRESS / COMPLETE",
    "The states that matter operationally are the blocking ones, because that is where vehicles actually sit and where the agent creates value."],
   ["The authorisation rule",
    "Repair cannot legitimately begin before the customer has said yes. That gate is why the release-claim rail exists."],
   ["QC failure is an edge, not an error path",
    "Quality control and road test can both send a job back to the bench, and supplementary work can re-open authorisation. A lifecycle that only moves forward does not describe a workshop."],
  ].forEach(([n2, sb], i) => card(s, M + i * (nw + 0.2), 5.18, nw, 0.94, "std", n2, sb, { ns: 10, ss: 8.5 }));

  s.addText("Amber marks the two blocking states; green marks the terminal one. The second row flows right to left, so every arrow drawn here is a transition the engine actually allows.", txt(null, {
    x: M, y: 6.3, w: FW, h: 0.3, fontSize: 9, italic: true, color: MUTE }));
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
