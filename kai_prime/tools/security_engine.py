"""Security Engine — vulnerability patterns, exploit templates, code scanning, and reporting."""
from __future__ import annotations
import json, logging, re, time
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("kai_prime.security")

EXT_TO_LANG = {
    ".py": "python", ".js": "javascript", ".ts": "typescript", ".php": "php",
    ".java": "java", ".cs": "csharp", ".rb": "ruby", ".go": "go",
    ".html": "html", ".jsp": "java", ".aspx": "csharp",
}


@dataclass
class VulnPattern:
    id: str = ""
    name: str = ""
    cwe: str = ""
    severity: str = ""
    languages: list[str] = field(default_factory=list)
    description: str = ""
    detection_regex: str = ""
    fix_pattern: str = ""
    references: list[str] = field(default_factory=list)
    cvss_score: float = 0.0

    def to_dict(self) -> dict:
        return {k: v for k, v in {
            "id": self.id, "name": self.name, "cwe": self.cwe,
            "severity": self.severity, "languages": self.languages,
            "description": self.description, "fix": self.fix_pattern,
            "cvss": self.cvss_score, "references": self.references[:3],
        }.items()}


@dataclass
class SecurityFinding:
    id: str = ""
    title: str = ""
    severity: str = ""
    category: str = ""
    location: str = ""
    description: str = ""
    evidence: str = ""
    impact: str = ""
    remediation: str = ""
    cvss_score: float = 0.0
    cwe: str = ""

    def to_dict(self) -> dict:
        return {k: v for k, v in {
            "id": self.id, "title": self.title, "severity": self.severity,
            "category": self.category, "location": self.location,
            "description": self.description, "evidence": self.evidence[:500],
            "impact": self.impact, "remediation": self.remediation,
            "cvss": self.cvss_score, "cwe": self.cwe,
        }.items()}


BUILTIN_PATTERNS = [
    VulnPattern("sqli_001", "SQL Injection (String Concat)", "CWE-89", "critical",
                ["python", "php", "java", "javascript", "csharp"],
                "SQL query built via string concat or f-string with user input.",
                r'(?:execute|query|cursor\.execute|Connection\.create)\s*\(\s*(?:f["\']|["\'].*%s|["\'].*\+|["\'].*\{)',
                "Use parameterized queries.", ["https://owasp.org/www-community/attacks/SQL_Injection"], 9.8),
    VulnPattern("xss_001", "Cross-Site Scripting (Reflected)", "CWE-79", "high",
                ["python", "javascript", "php", "java", "csharp"],
                "User input directly rendered in HTML without sanitization.",
                r'(?:innerHTML|document\.write|dangerouslySetInnerHTML|Response\.Write|echo\s+\$_GET|\.html\(.*\+)',
                "Use textContent or auto-escaping templates.", ["https://owasp.org/www-community/attacks/xss/"], 7.5),
    VulnPattern("cmdi_001", "OS Command Injection", "CWE-78", "critical",
                ["python", "php", "javascript", "ruby", "bash"],
                "User input passed to shell command execution.",
                r'(?:os\.system|subprocess\.(?:call|run|Popen)|exec\(|passthru\(|shell_exec\(|`.*\$\{)',
                "Use subprocess with list args, no shell=True.", ["https://owasp.org/www-community/attacks/Command_Injection"], 9.8),
    VulnPattern("path_001", "Path Traversal", "CWE-22", "high",
                ["python", "php", "java", "javascript", "csharp"],
                "User input used in file path without validation.",
                r'(?:open|read_file|include|require|send_file)\s*\(\s*(?:.*\+.*path|.*f["\'].*\{|.*\.\.\/)',
                "Validate paths: os.path.abspath(os.path.join(base, user_input)).startswith(base)", ["https://owasp.org/www-community/attacks/Path_Traversal"], 7.5),
    VulnPattern("deser_001", "Insecure Deserialization", "CWE-502", "critical",
                ["python", "java", "php"],
                "Untrusted data passed to pickle.loads, yaml.load, or unserialize.",
                r'(?:pickle\.loads|yaml\.load\s*\([^,)]+\)|marshal\.loads|unserialize\s*\(|ObjectInputStream)',
                "Use yaml.safe_load(). Never pickle untrusted data.", ["https://cwe.mitre.org/data/definitions/502.html"], 9.8),
    VulnPattern("secret_001", "Hardcoded Secret / API Key", "CWE-798", "high",
                ["python", "javascript", "java", "csharp", "go", "ruby"],
                "API keys or passwords hardcoded in source code.",
                r'(?:api_key|apikey|secret_key|password|token|auth_token)\s*=\s*["\'][A-Za-z0-9_\-]{16,}["\']',
                "Use environment variables or secrets manager.", ["https://cwe.mitre.org/data/definitions/798.html"], 7.4),
    VulnPattern("ssrf_001", "Server-Side Request Forgery", "CWE-918", "high",
                ["python", "php", "java", "javascript", "go"],
                "User-controlled URL used in server-side HTTP request.",
                r'(?:requests\.(?:get|post|put|delete)|urllib\.request\.urlopen|fetch\s*\(|http\.Get)\s*\(\s*(?:.*\+|.*f["\']|.*req\.|.*params)',
                "Validate URLs against allowlist. Block internal IPs.", ["https://owasp.org/www-community/attacks/Server_Side_Request_Forgery"], 8.6),
    VulnPattern("idor_001", "Insecure Direct Object Reference", "CWE-639", "medium",
                ["python", "php", "java", "javascript", "csharp"],
                "Object ID from user input used without authorization check.",
                r'(?:get_object|find_by_id|where.*id\s*=\s*request|params\[:id\]|req\.params\.id)',
                "Add authorization check.", ["https://cwe.mitre.org/data/definitions/639.html"], 6.5),
    VulnPattern("crypto_001", "Weak Cryptographic Algorithm", "CWE-327", "medium",
                ["python", "javascript", "java", "csharp", "go"],
                "Use of MD5, SHA1, DES, or RC4.",
                r'(?:MD5\.|SHA1\.|DES\.|RC4\.|md5\(|sha1\(|hashlib\.md5|hashlib\.sha1)',
                "Use SHA-256+ or AES-256-GCM.", ["https://cwe.mitre.org/data/definitions/327.html"], 5.9),
    VulnPattern("xxe_001", "XML External Entity (XXE)", "CWE-611", "high",
                ["python", "java", "php", "csharp"],
                "XML parsing without disabling external entity resolution.",
                r'(?:xml\.parse|XMLParser|SAXParser|DocumentBuilder|simplexml_load_string)\s*\(',
                "Disable external entities. Use defusedxml.", ["https://cwe.mitre.org/data/definitions/611.html"], 7.5),
]


class SecurityEngine:
    def __init__(self, workspace: Path):
        self.workspace = workspace
        self._path = workspace / "kai_prime_data" / "security_knowledge.json"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self.vuln_patterns: list[VulnPattern] = []
        self._load()
        if not self.vuln_patterns:
            self.vuln_patterns = list(BUILTIN_PATTERNS)
            self._save()

    def _load(self):
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self.vuln_patterns = [VulnPattern(**v) for v in data.get("vuln_patterns", [])]
            except Exception:
                pass

    def _save(self):
        try:
            self._path.write_text(json.dumps({
                "vuln_patterns": [v.to_dict() for v in self.vuln_patterns],
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }, indent=2), encoding="utf-8")
        except Exception:
            pass

    def scan_code(self, code: str, language: str = "python") -> list[SecurityFinding]:
        findings = []
        for pat in self.vuln_patterns:
            if language not in pat.languages:
                continue
            try:
                for match in re.finditer(pat.detection_regex, code, re.IGNORECASE):
                    line_num = code[:match.start()].count("\n") + 1
                    line = code.split("\n")[line_num - 1].strip()
                    findings.append(SecurityFinding(
                        id=f"{pat.id}_L{line_num}", title=pat.name, severity=pat.severity,
                        category=pat.cwe.split("-")[-1], location=f"line {line_num}",
                        description=pat.description, evidence=line[:300],
                        impact=self._impact(pat.severity), remediation=pat.fix_pattern,
                        cvss_score=pat.cvss_score, cwe=pat.cwe,
                    ))
            except re.error:
                continue
        findings.sort(key=lambda f: f.cvss_score, reverse=True)
        return findings

    def scan_file(self, path: str | Path) -> list[SecurityFinding]:
        p = Path(path)
        if not p.exists():
            return []
        ext = p.suffix.lower()
        lang = EXT_TO_LANG.get(ext, "python")
        code = p.read_text(encoding="utf-8", errors="replace")
        findings = self.scan_code(code, lang)
        for f in findings:
            f.location = f"{p.name}:{f.location}"
        return findings

    def scan_project(self, root: str | Path) -> list[SecurityFinding]:
        root = Path(root)
        all_findings = []
        skip = {"node_modules", "venv", ".venv", "__pycache__", ".git", "dist", "build"}
        for fp in root.rglob("*"):
            if fp.is_file() and fp.suffix.lower() in EXT_TO_LANG:
                if any(s in fp.parts for s in skip):
                    continue
                try:
                    all_findings.extend(self.scan_file(fp))
                except Exception:
                    continue
        all_findings.sort(key=lambda f: f.cvss_score, reverse=True)
        return all_findings

    def build_report(self, findings: list[SecurityFinding], target: str = "") -> dict:
        counts = {}
        for f in findings:
            counts[f.severity] = counts.get(f.severity, 0) + 1
        risk = sum({"critical": 10, "high": 8, "medium": 5, "low": 2, "info": 1}.get(f.severity, 0) for f in findings)
        recs = list({f.remediation for f in findings})[:10]
        return {
            "target": target, "total_findings": len(findings),
            "severity": counts, "risk_score": risk,
            "risk_level": "critical" if risk >= 50 else "high" if risk >= 30 else "medium" if risk >= 15 else "low",
            "findings": [f.to_dict() for f in findings], "recommendations": recs,
        }

    def search_vulns(self, query: str) -> list[dict]:
        q = query.lower()
        return [p.to_dict() for p in self.vuln_patterns if q in f"{p.name} {p.description} {p.cwe}".lower()]

    def status(self) -> dict:
        return {"patterns": len(self.vuln_patterns),
                "languages": sorted(set(l for p in self.vuln_patterns for l in p.languages))}

    @staticmethod
    def _impact(severity: str) -> str:
        return {"critical": "Full compromise possible.", "high": "Significant security impact.",
                "medium": "Moderate risk.", "low": "Minor issue.", "info": "Informational."}.get(severity, "Unknown.")
