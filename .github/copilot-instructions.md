# Copilot Code Review Instructions

Universal guidance for automated code reviews. Prioritize real bugs and security over style preferences.

## Do Flag

### Bugs

- Logic errors — incorrect calculations, off-by-one, wrong comparisons
- Null/undefined access without guards
- Race conditions or async handling errors
- Unreachable code or dead branches
- Broken error handling (swallowed exceptions, missing catches)

### Security

- XSS — unescaped user input in HTML/JSX
- Injection — string concatenation in SQL, shell commands, or eval
- Secrets — API keys, passwords, tokens in code or logs
- Auth issues — missing or bypassable authorization checks
- Insecure dependencies — known vulnerabilities in packages

### Accessibility

- Missing alt text on images
- Missing form labels or aria-labels
- Broken keyboard navigation (non-focusable interactive elements)
- Insufficient color contrast (when detectable)
- Missing skip links or landmark regions

### Correctness

- Type mismatches (in typed languages)
- Incorrect API usage (wrong method signatures, missing required params)
- Resource leaks (unclosed connections, missing cleanup)

## Do Not Flag

### Premature Optimization

- Missing `useMemo`/`useCallback` without measured performance issue
- "Could be more efficient" when current code is readable and fast enough
- Suggesting caching without evidence of repeated expensive computation

### Over-Engineering

- Extracting helpers/utilities for code used only once or twice
- Suggesting abstractions for "future flexibility"
- Adding configuration for hardcoded values that won't change
- Proposing design patterns that add complexity without clear benefit
- Thread safety guards (locks, queues, dedup sets) for single-user scripts or tools
- Defensive re-entry guards (`if not logger.handlers`) for functions called exactly once in `main()`
- Backward-compatibility shims for renaming fields in brand-new config formats

### Style Preferences

- Naming suggestions unless current name is actively misleading
- Formatting issues (defer to linter/formatter)
- "Could be cleaner" without concrete improvement
- Preferring one valid approach over another equally valid one

### Intentional Patterns

- Patterns documented in project CLAUDE.md or style guide
- Framework-specific idioms (even if unfamiliar)
- Explicit trade-offs noted in comments

### Previously Addressed

- Do not re-raise concerns that have been dismissed in resolved review threads on the same PR

### Non-Issues

- TODOs or FIXMEs (these are intentional markers)
- `console.log` in CLI scripts and build tools (use `console.debug` for temporary debugging in app code)
- Magic numbers that are obvious in context (HTTP status codes, etc.)

---

## Project-Specific: Clip Forge (Python CLI)

This is a Python CLI pipeline — no web frontend. Web-specific rules (XSS, JSX, useMemo, aria) do not apply.

### Do Flag

- Subprocess calls using string interpolation or `shell=True` (command injection risk)
- File paths built with string concatenation instead of `pathlib` or `os.path.join`
- JSON/config files opened with `encoding="utf-8"` instead of `utf-8-sig` (BOM risk from PowerShell-written files)
- FFmpeg or ffprobe invocations that don't check return codes

### Do Not Flag

- Hardcoded Windows paths (this tool is Windows-only by design — DaVinci Resolve scripting requires it)
- Python 3.8-specific syntax in `resolve_*.py` files (required by `fusionscript.dll` ABI)
- Print statements in CLI scripts (intentional user-facing output)
