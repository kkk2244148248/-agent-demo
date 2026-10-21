"""密钥 / 敏感信息扫描器（只输出脱敏摘要，不打印原文）"""
import re
import subprocess
import sys

PATTERNS = [
    ("OpenAI/DashScope Key", re.compile(r"sk-[A-Za-z0-9_\-]{16,}")),
    ("千问/阿里 Key", re.compile(r"sk-[A-Za-z0-9]{20,}")),
    ("通用 API Key 赋值", re.compile(r"(?i)(api[_-]?key|apikey|secret[_-]?key|access[_-]?key)\s*[:=]\s*[\"']?([A-Za-z0-9_\-]{12,})")),
    ("密码赋值", re.compile(r"(?i)(password|passwd|pwd)\s*[:=]\s*[\"']?([^\s\"',}]{4,})")),
    ("数据库连接串", re.compile(r"(?i)(mysql|postgres|redis|mongodb)://[^\s\"']+")),
    ("Bearer Token", re.compile(r"(?i)bearer\s+[A-Za-z0-9_\-\.]{20,}")),
    ("私钥", re.compile(r"-----BEGIN (RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----")),
    ("GitHub Token", re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}")),
]

# 明确是占位符/示例的，判为安全
SAFE_HINTS = (
    "your_", "xxx", "***", "example", "changeme", "placeholder",
    "<", ">", "os.getenv", "os.environ", "getenv", "settings.", "${",
    "localhost", "127.0.0.1", "test", "dummy", "mock", "none", "null",
    "0123456", "123456", "password=",  # 示例账号
)

SKIP_EXT = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".woff", ".woff2",
            ".ttf", ".eot", ".zip", ".pdf", ".lock", ".mp4"}


def mask(v: str) -> str:
    v = v.strip().strip("\"'")
    if len(v) <= 6:
        return "***"
    return f"{v[:3]}***{v[-2:]}(len={len(v)})"


def scan_text(text: str, label: str, findings: list):
    for name, pat in PATTERNS:
        for m in pat.finditer(text):
            raw = m.group(0)
            low = raw.lower()
            if any(h in low for h in SAFE_HINTS):
                continue
            # 取最后一组（值部分）
            val = m.group(m.lastindex) if m.lastindex else raw
            findings.append((label, name, mask(val), raw[:80]))


def scan_worktree():
    out = subprocess.run(["git", "ls-files"], capture_output=True, text=True, encoding="utf-8").stdout
    findings = []
    for f in out.splitlines():
        if any(f.lower().endswith(e) for e in SKIP_EXT):
            continue
        try:
            text = open(f, encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
        scan_text(text, f, findings)
    return findings


def scan_history():
    # 逐提交扫 diff 的新增行，能定位到具体 commit
    log = subprocess.run(
        ["git", "log", "--all", "-p", "--unified=0", "--pretty=format:@@COMMIT@@%h|%ad|%s", "--date=short"],
        capture_output=True, text=True, encoding="utf-8", errors="ignore",
    ).stdout
    findings = []
    cur = "?"
    for line in log.splitlines():
        if line.startswith("@@COMMIT@@"):
            cur = line.replace("@@COMMIT@@", "")
            continue
        if line.startswith("+") and not line.startswith("+++"):
            scan_text(line[1:], cur, findings)
    return findings


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    wt = scan_worktree() if mode in ("all", "wt") else []
    hist = scan_history() if mode in ("all", "hist") else []

    print(f"### 工作区命中 {len(wt)} 处")
    for f, name, val, ctx in wt[:40]:
        print(f"  [{name}] {f} → {val}")

    print(f"\n### 历史提交命中 {len(hist)} 处")
    seen = set()
    for commit, name, val, ctx in hist:
        k = (commit.split("|")[0], name, val)
        if k in seen:
            continue
        seen.add(k)
        print(f"  [{name}] {commit} → {val}")
    print(f"\n历史去重后 {len(seen)} 条唯一命中")
