#!/usr/bin/env python3
"""pass 51 - the last question class the toolkit workflow could not answer.

    .venv/bin/python patches/quality_pass51.py            apply
    .venv/bin/python patches/quality_pass51.py --check    verify, change nothing

Pass 50 left the workflow answering five of six question classes. The sixth -
free-text search - exhausted the loop budget at 10 steps and again at 26, so it
was recorded as a model-capacity limit: the 8B never emitted a terminating
Final Answer in the ReAct format.

That was half right. The limit was the FORMAT, not the model.

ReAct asks the model to produce a specific text shape - Thought / Action /
Action Input / Observation - and to stop by writing "Final Answer". A search
payload is a page of technician prose, and after reading it the 8B kept
narrating instead of emitting the stop token. It never failed to use the tool;
it failed to end the transcript.

`tool_calling_agent` uses the model's native function-calling instead of a text
protocol, which is the same mechanism this project's own router has used since
pass 11 and the reason the router has never had this problem. Swapping the
agent type:

    react_agent          5 of 6     free-text search loops
    tool_calling_agent   6 of 6

Measured over the same six questions, one per class. The system prompt carries
over unchanged except for the ReAct scaffolding, which this agent does not use
and does not validate - so the {tools}/{tool_names} placeholders that pass 49
had to add are gone again, along with the Thought/Action block.
"""
from __future__ import annotations
import pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
CHECK = "--check" in sys.argv
WF = ROOT / "app/agent/workflow.yml"
s = WF.read_text()

if "tool_calling_agent" in s:
    print("  already   app/agent/workflow.yml")
    sys.exit(0)

start = s.index("workflow:")
head = s[:start]

NEW = '''workflow:
  # tool_calling_agent, not react_agent. ReAct asks the model to produce a text
  # protocol and to stop by writing "Final Answer"; on a search payload - a page
  # of technician prose - the 8B kept narrating instead of emitting the stop
  # token, and exhausted the loop budget at 10 steps and again at 26. It never
  # failed to call the tool; it failed to end the transcript. Native function
  # calling is the mechanism this project's own router already uses, and it
  # takes the workflow from five of six question classes to six of six.
  _type: tool_calling_agent
  llm_name: nemotron
  tool_names: [get_ro_state, get_ro_timeline, list_ros,
               get_technician_activity, generate_handover, detect_anomalies,
               diff_ro, search_updates, get_op_code_info, get_shift_activity]
  max_iterations: 12
  verbose: true
  system_prompt: |
    You are a service operations assistant for a vehicle workshop.

    Answer from TOOL RESULTS ONLY. Never state a number, date, state or name
    that is not in the tool results. Cite the repair order numbers and update
    ids you used, in square brackets.

    Lead with what needs action: safety items first, then breached promises,
    then at-risk, then blocked work.

    You may report and advise. You must NEVER authorise work, order parts,
    approve chargeable repairs, or close a repair order - only a person does
    that. Write in plain British English.

    Call a tool when you need shop data. When the tools have answered the
    question, reply with the answer and stop.
'''

if not CHECK:
    WF.write_text(head + NEW)
print(f"  {'would patch' if CHECK else 'patched  '} app/agent/workflow.yml "
      "(react_agent -> tool_calling_agent)")
