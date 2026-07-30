"""Reasoning Framework — ReAct, Tree of Thoughts, Self-Reflection."""
from __future__ import annotations
import json, re, logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger("kai_prime.reasoning")


@dataclass
class Thought:
    id: int
    content: str
    type: str  # thought, action, observation, reflection
    parent_id: int | None = None
    depth: int = 0
    score: float = 0.0
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


@dataclass
class ReasoningTrace:
    task: str
    framework: str
    thoughts: list[Thought] = field(default_factory=list)
    result: str = ""
    success: bool = False
    steps_taken: int = 0
    start_time: str = ""
    end_time: str = ""
    duration_seconds: float = 0.0

    def to_dict(self) -> dict:
        return {
            "task": self.task, "framework": self.framework,
            "thoughts": [{"id": t.id, "content": t.content[:200], "type": t.type, "score": t.score, "depth": t.depth} for t in self.thoughts],
            "result": self.result, "success": self.success, "steps_taken": self.steps_taken,
            "duration_seconds": self.duration_seconds,
        }


class ReActAgent:
    MAX_ITERATIONS = 8

    def __init__(self, ask_fn: Callable[[str], str], workspace: Path | None = None):
        self.ask_fn = ask_fn
        self.workspace = workspace
        self.tools: dict[str, Callable] = {}

    def register_tool(self, name: str, fn: Callable):
        self.tools[name] = fn

    def run(self, task: str) -> ReasoningTrace:
        trace = ReasoningTrace(task=task, framework="react", start_time=datetime.now(timezone.utc).isoformat())
        tools_str = "\n".join(f"  - {n}: {d}" for n, d in self.tools.items()) if self.tools else "  (no custom tools)"
        system = (
            f"Solve this step by step using ReAct reasoning:\n\nTask: {task}\n\n"
            f"Available actions: read_file, run_command, web_search, browse_url, {tools_str}\n\n"
            f"Use this format strictly:\nThought: [reasoning]\nAction: [action_name] [args]\n"
            f"Observation: [filled by system]\n...\nFinal Answer: [complete answer]\n\n"
            f"Rules: think before each action, one action per step, max {self.MAX_ITERATIONS} steps."
        )
        history = [{"role": "system", "content": system}]

        for iteration in range(1, self.MAX_ITERATIONS + 1):
            trace.steps_taken = iteration
            prompt = f"\n--- Step {iteration} ---\nContinue reasoning:"
            history.append({"role": "user", "content": prompt})
            full = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in history)
            response = self.ask_fn(full)

            thought_m = re.search(r"Thought:\s*(.+?)(?=Action:|Observation:|Final Answer:|$)", response, re.DOTALL)
            action_m = re.search(r"Action:\s*(.+?)(?=Observation:|Thought:|Final Answer:|$)", response, re.DOTALL)
            answer_m = re.search(r"Final Answer:\s*(.+?)(?=$)", response, re.DOTALL)

            if thought_m:
                trace.thoughts.append(Thought(id=iteration * 3 - 2, content=thought_m.group(1).strip(), type="thought", depth=iteration))

            if answer_m:
                trace.result = answer_m.group(1).strip()
                trace.success = True
                break

            if action_m:
                action_str = action_m.group(1).strip()
                parts = action_str.split(None, 1)
                action_name = parts[0].lower()
                args = parts[1] if len(parts) > 1 else ""
                observation = "Unknown action."
                if action_name in self.tools:
                    try:
                        observation = str(self.tools[action_name](**{k: v for k, v in [a.split("=", 1)] if len(a.split("=", 1)) == 2}) if "=" in args else self.tools[action_name](args))
                    except Exception as e:
                        observation = f"Tool error: {e}"
                elif action_name in ("read_file", "run_command", "web_search", "browse_url"):
                    observation = f"Use the registered tool: {action_name}({args})"
                trace.thoughts.append(Thought(id=iteration * 3 - 1, content=action_str, type="action", depth=iteration))
                trace.thoughts.append(Thought(id=iteration * 3, content=observation[:500], type="observation", depth=iteration))
                history.append({"role": "user", "content": f"Action: {action_str}\nObservation: {observation}"})

        trace.end_time = datetime.now(timezone.utc).isoformat()
        try:
            trace.duration_seconds = round((datetime.fromisoformat(trace.end_time) - datetime.fromisoformat(trace.start_time)).total_seconds(), 2)
        except Exception:
            pass
        if not trace.success:
            trace.result = f"Reached max iterations ({self.MAX_ITERATIONS}) without final answer."
        return trace


class SelfReflector:
    def __init__(self, ask_fn: Callable[[str], str]):
        self.ask_fn = ask_fn

    def reflect(self, task: str, output: str) -> ReasoningTrace:
        trace = ReasoningTrace(task=f"Reflect on: {task}", framework="reflection", start_time=datetime.now(timezone.utc).isoformat())
        critique = self.ask_fn(f"Task: {task}\n\nOutput:\n{output[:2000]}\n\nCritically analyze. Identify errors, missing info, logic flaws. Be specific.")
        trace.thoughts.append(Thought(id=1, content=critique[:500], type="reflection"))
        improved = self.ask_fn(f"Original:\n{output[:2000]}\n\nReview:\n{critique[:1000]}\n\nGenerate improved version addressing all issues.")
        trace.thoughts.append(Thought(id=2, content=improved[:500], type="thought"))
        trace.result = improved
        trace.success = True
        trace.steps_taken = 3
        trace.end_time = datetime.now(timezone.utc).isoformat()
        return trace


class ReasoningFramework:
    def __init__(self, ask_fn: Callable[[str], str], workspace: Path | None = None):
        self.ask_fn = ask_fn
        self.react = ReActAgent(ask_fn, workspace)
        self.reflection = SelfReflector(ask_fn)
        self.history: list[ReasoningTrace] = []

    def reason(self, task: str, framework: str = "auto", **kwargs) -> ReasoningTrace:
        if framework == "auto":
            task_lower = task.lower()
            if any(kw in task_lower for kw in ["review", "improve", "critique", "better"]):
                framework = "reflection"
            else:
                framework = "react"

        if framework == "reflection":
            trace = self.reflection.reflect(task, kwargs.get("output", ""))
        else:
            trace = self.react.run(task)

        self.history.append(trace)
        self._save_trace(trace)
        return trace

    def _save_trace(self, trace: ReasoningTrace):
        if not self.workspace:
            return
        traces_dir = self.workspace / "kai_prime_data" / "memory" / "reasoning_traces"
        traces_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        path = traces_dir / f"trace_{trace.framework}_{ts}.json"
        try:
            path.write_text(json.dumps(trace.to_dict(), indent=2), encoding="utf-8")
        except Exception:
            pass

    def get_history(self, limit: int = 10) -> list[dict]:
        return [t.to_dict() for t in self.history[-limit:]]
