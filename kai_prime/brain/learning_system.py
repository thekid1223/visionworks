"""Kai Learning System — self-improving skills and memory.

Closes the AI learning and memory gaps with procedural learning.
"""
import json
import hashlib
import threading
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field, asdict
from datetime import datetime


@dataclass
class LearnedSkill:
    id: str
    name: str
    description: str
    category: str
    confidence: float = 0.5
    usage_count: int = 0
    success_rate: float = 0.0
    last_used: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    successful_executions: List[Dict] = field(default_factory=list)
    failed_executions: List[Dict] = field(default_factory=list)
    learned_patterns: List[str] = field(default_factory=list)
    improvement_suggestions: List[str] = field(default_factory=list)
    steps: List[str] = field(default_factory=list)
    prerequisites: List[str] = field(default_factory=list)
    variations: Dict[str, List[str]] = field(default_factory=dict)

    def record_success(self, execution_data: Dict):
        self.usage_count += 1
        self.last_used = datetime.now().isoformat()
        self.successful_executions.append(execution_data)
        self._update_metrics()

    def record_failure(self, execution_data: Dict):
        self.usage_count += 1
        self.last_used = datetime.now().isoformat()
        self.failed_executions.append(execution_data)
        self._update_metrics()

    def _update_metrics(self):
        total = len(self.successful_executions) + len(self.failed_executions)
        if total > 0:
            self.success_rate = len(self.successful_executions) / total
            usage_factor = min(1.0, self.usage_count / 10.0)
            self.confidence = (self.success_rate * 0.7) + (usage_factor * 0.3)

    def add_pattern(self, pattern: str):
        if pattern not in self.learned_patterns:
            self.learned_patterns.append(pattern)

    def add_improvement(self, suggestion: str):
        if suggestion not in self.improvement_suggestions:
            self.improvement_suggestions.append(suggestion)


class KaiLearningSystem:

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self._data_dir = workspace / "kai_prime_data" / "learning"
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.skills: Dict[str, LearnedSkill] = {}
        self._load_skills()

    def _load_skills(self):
        skills_dir = self._data_dir / "skills"
        if not skills_dir.exists():
            return
        for f in skills_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                self.skills[data["id"]] = LearnedSkill(**data)
            except Exception:
                pass

    def _save_skill(self, skill: LearnedSkill):
        skills_dir = self._data_dir / "skills"
        skills_dir.mkdir(exist_ok=True)
        (skills_dir / f"{skill.id}.json").write_text(
            json.dumps(asdict(skill), indent=2, ensure_ascii=False),
            encoding="utf-8"
        )

    def create_skill(self, name: str, description: str, category: str,
                     steps: List[str] = None, context: Dict = None) -> LearnedSkill:
        with self._lock:
            existing = self._find_similar(name)
            if existing:
                execution_data = {
                    "steps_count": len(steps or []),
                    "context": context or {},
                    "timestamp": datetime.now().isoformat()
                }
                existing.record_success(execution_data)
                self._save_skill(existing)
                return existing

            skill_id = hashlib.md5(name.encode()).hexdigest()[:8]
            skill = LearnedSkill(
                id=skill_id,
                name=name,
                description=description,
                category=category,
                steps=steps or [],
                confidence=0.6
            )
            execution_data = {
                "steps_count": len(steps or []),
                "context": context or {},
                "timestamp": datetime.now().isoformat()
            }
            skill.record_success(execution_data)
            self.skills[skill.id] = skill
            self._save_skill(skill)
            return skill

    def record_success(self, skill_id: str, context: Dict = None):
        with self._lock:
            skill = self.skills.get(skill_id)
            if skill:
                skill.record_success({
                    "context": context or {},
                    "timestamp": datetime.now().isoformat()
                })
                self._save_skill(skill)

    def record_failure(self, skill_id: str, context: Dict = None):
        with self._lock:
            skill = self.skills.get(skill_id)
            if skill:
                skill.record_failure({
                    "context": context or {},
                    "timestamp": datetime.now().isoformat()
                })
                self._save_skill(skill)

    def list_skills(self, category: str = None) -> List[LearnedSkill]:
        skills = list(self.skills.values())
        if category:
            skills = [s for s in skills if s.category == category]
        skills.sort(key=lambda s: (s.confidence, s.usage_count), reverse=True)
        return skills

    def get_skill(self, skill_id: str) -> Optional[LearnedSkill]:
        return self.skills.get(skill_id)

    def improve_skills(self):
        with self._lock:
            for skill in self.skills.values():
                if skill.usage_count >= 3:
                    if skill.success_rate < 0.8 and skill.usage_count >= 5:
                        skill.add_improvement("Improve reliability - success rate below 80%")
                    failed_count = len(skill.failed_executions)
                    if failed_count > 0:
                        skill.add_improvement(f"Address {failed_count} failed executions")
                    if skill.usage_count >= 10 and skill.confidence < 0.7:
                        skill.add_improvement("Increase confidence through more successful executions")
                    self._save_skill(skill)

    def get_stats(self) -> Dict[str, Any]:
        total = len(self.skills)
        if total > 0:
            avg_conf = sum(s.confidence for s in self.skills.values()) / total
            avg_rate = sum(s.success_rate for s in self.skills.values()) / total
            total_usage = sum(s.usage_count for s in self.skills.values())
        else:
            avg_conf = avg_rate = total_usage = 0
        categories = {}
        for s in self.skills.values():
            categories[s.category] = categories.get(s.category, 0) + 1
        return {
            "total_skills": total,
            "average_confidence": round(avg_conf, 2),
            "average_success_rate": round(avg_rate, 2),
            "total_usage": total_usage,
            "categories": categories,
        }

    def _find_similar(self, name: str) -> Optional[LearnedSkill]:
        name_lower = name.lower()
        for skill in self.skills.values():
            if skill.name.lower() == name_lower:
                return skill
            skill_words = set(skill.name.lower().split())
            name_words = set(name_lower.split())
            union = skill_words | name_words
            if union and len(skill_words & name_words) / len(union) > 0.6:
                return skill
        return None
