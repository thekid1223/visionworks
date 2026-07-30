"""Confidence Scorer v2 — hybrid regex + LLM response quality scoring.

Fast regex path runs first. If score is borderline (0.4-0.7), an optional
cheap LLM call refines the score for better accuracy. Self-improves by
learning which patterns actually matter from outcome ledger feedback.
"""
from __future__ import annotations

import json
import time
import threading
import logging
from pathlib import Path
from typing import Callable

log = logging.getLogger("kai_prime.confidence")


class ConfidenceScorer:

    def __init__(self, workspace: Path | None = None, llm_call: Callable | None = None):
        self._llm_call = llm_call
        self._reg_weights = {
            "too_short": 0.3,
            "echo": 0.4,
            "hallucinated_scan": 0.5,
            "contradiction": 0.3,
            "vague_promise": 0.2,
            "punctuation_only": 0.6,
            "raw_json": 0.5,
            "error_leak": 0.6,
            "unsolicited_code": 0.3,
            "refusal_pattern": 0.5,
        }
        # Learned weights from outcome ledger feedback
        self._learned_weights: dict[str, float] = {}
        self._lock = threading.Lock()
        self._call_count = 0
        self._llm_call_count = 0
        self._weights_file = workspace / "kai_prime_data" / "confidence_weights.json" if workspace else None
        self._load_weights()

    def _load_weights(self):
        if self._weights_file and self._weights_file.exists():
            try:
                data = json.loads(self._weights_file.read_text(encoding="utf-8"))
                self._learned_weights = data.get("learned_weights", {})
            except Exception:
                pass

    def _save_weights(self):
        if self._weights_file:
            try:
                self._weights_file.parent.mkdir(parents=True, exist_ok=True)
                self._weights_file.write_text(json.dumps({
                    "learned_weights": self._learned_weights,
                    "total_calls": self._call_count,
                    "llm_calls": self._llm_call_count,
                }, indent=2), encoding="utf-8")
            except Exception:
                pass

    def learn_from_outcome(self, reply: str, user_input: str, was_successful: bool):
        """Adjust weights based on whether a low-confidence reply was actually good."""
        issues = self._regex_diagnose(reply, user_input)
        adjustment = 0.05 if was_successful else -0.05
        with self._lock:
            for issue in issues:
                current = self._learned_weights.get(issue, 0.0)
                self._learned_weights[issue] = max(-0.3, min(0.3, current + adjustment))
            self._save_weights()

    def score(self, reply: str, user_input: str) -> float:
        self._call_count += 1
        score = self._regex_score(reply, user_input)

        # If borderline, use cheap LLM to refine
        if 0.4 < score < 0.7 and self._llm_call:
            self._llm_call_count += 1
            llm_score = self._llm_score(reply, user_input)
            if llm_score is not None:
                score = (score + llm_score) / 2

        return max(0.0, score)

    def is_confident(self, reply: str, user_input: str, threshold: float = 0.5) -> bool:
        return self.score(reply, user_input) >= threshold

    def diagnose(self, reply: str, user_input: str) -> list[str]:
        issues = self._regex_diagnose(reply, user_input)
        # Filter out issues where learned weight says they don't matter
        return [i for i in issues if self._effective_weight(i) > 0.05]

    def _effective_weight(self, issue: str) -> float:
        learned = self._learned_weights.get(issue, 0.0)
        base = self._reg_weights.get(issue, 0.3)
        return max(0.0, base + learned)

    def _regex_score(self, reply: str, user_input: str) -> float:
        score = 1.0
        r_lower = reply.lower().strip()
        u_lower = user_input.lower().strip()
        r_words = r_lower.split()
        u_words = u_lower.split()

        if len(r_words) < 5:
            score -= self._effective_weight("too_short")
        overlap = len(set(r_words) & set(u_words))
        if u_words and overlap / max(len(set(u_words)), 1) > 0.6:
            score -= self._effective_weight("echo")
        if r_lower == u_lower:
            score -= self._effective_weight("echo")

        scan_hallucinations = ["nmap result", "open ports", "vulnerability found",
                               "port scan", "syn scan", "service scan"]
        scan_intent = any(p in u_lower for p in ["scan", "nmap", "port", "vuln",
                                                  "hunt", "probe", "recon"])
        if any(p in r_lower for p in scan_hallucinations) and not scan_intent:
            score -= self._effective_weight("hallucinated_scan")
        if "here's what i found" in r_lower and "couldn't find" in r_lower:
            score -= self._effective_weight("contradiction")
        if "yes" in r_lower and "no" in r_lower and len(r_words) < 20:
            score -= self._effective_weight("contradiction")
        if len(r_words) < 15 and any(p in r_lower for p in ["i'll look", "let me",
                                                              "i will", "i can try"]):
            score -= self._effective_weight("vague_promise")
        if all(c in ".,!? \n" for c in reply.strip()):
            score -= self._effective_weight("punctuation_only")
        if reply.strip().startswith("[") and reply.strip().endswith("]"):
            score -= self._effective_weight("raw_json")
        error_patterns = ["traceback", "winerror", "runtimeerror", "attributeerror",
                          "modulenotfounderror", "importerror"]
        if any(p in r_lower for p in error_patterns):
            score -= self._effective_weight("error_leak")
        # Unsolicited code blocks
        if "```" in reply and not any(p in u_lower for p in ["code", "script", "syntax", "example", "write"]):
            score -= self._effective_weight("unsolicited_code")
        # Refusal patterns
        if any(p in r_lower for p in ["i cannot", "i'm not able", "i am not able", "it's not appropriate"]):
            score -= self._effective_weight("refusal_pattern")

        return max(0.0, score)

    def _regex_diagnose(self, reply: str, user_input: str) -> list[str]:
        issues = []
        r_lower = reply.lower().strip()
        u_lower = user_input.lower().strip()
        r_words = r_lower.split()
        u_words = u_lower.split()

        if len(r_words) < 5:
            issues.append("too_short")
        overlap = len(set(r_words) & set(u_words))
        if u_words and overlap / max(len(set(u_words)), 1) > 0.6:
            issues.append("echo")
        if r_lower == u_lower:
            issues.append("exact_echo")
        scan_hallucinations = ["nmap result", "open ports", "vulnerability found",
                               "port scan", "syn scan", "service scan"]
        scan_intent = any(p in u_lower for p in ["scan", "nmap", "port", "vuln", "hunt", "probe", "recon"])
        if any(p in r_lower for p in scan_hallucinations) and not scan_intent:
            issues.append("hallucinated_scan")
        if "here's what i found" in r_lower and "couldn't find" in r_lower:
            issues.append("contradiction")
        if len(r_words) < 15 and any(p in r_lower for p in ["i'll look", "let me", "i will", "i can try"]):
            issues.append("vague_promise")
        if all(c in ".,!? \n" for c in reply.strip()):
            issues.append("punctuation_only")
        if reply.strip().startswith("[") and reply.strip().endswith("]"):
            issues.append("raw_json")
        error_patterns = ["traceback", "winerror", "runtimeerror", "attributeerror",
                          "modulenotfounderror", "importerror"]
        if any(p in r_lower for p in error_patterns):
            issues.append("error_leak")
        if "```" in reply and not any(p in u_lower for p in ["code", "script", "syntax", "example", "write"]):
            issues.append("unsolicited_code")
        if any(p in r_lower for p in ["i cannot", "i'm not able", "i am not able", "it's not appropriate"]):
            issues.append("refusal_pattern")
        return issues

    def _llm_score(self, reply: str, user_input: str) -> float | None:
        if not self._llm_call:
            return None
        try:
            prompt = f"Reply: {reply[:500]}\nUser: {user_input[:500]}\nRate the reply quality 0-1:"
            result = self._llm_call(prompt)
            for val in result.split():
                try:
                    f = float(val.strip("., "))
                    if 0 <= f <= 1:
                        return f
                except ValueError:
                    continue
            return None
        except Exception:
            return None

    def status(self) -> dict:
        return {
            "calls": self._call_count,
            "llm_refinements": self._llm_call_count,
            "learned_patterns": len(self._learned_weights),
            "active_patterns": {k: round(self._effective_weight(k), 3) for k in self._reg_weights},
        }
