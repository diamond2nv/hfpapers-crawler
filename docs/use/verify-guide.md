# hfpclawer Verify Module — User Guide

## Overview

The `hfpclawer.verify` module implements a **5-layer formula verification pipeline**:

| Layer | Engine | Dependency | Zero-Config? | Purpose |
|:------|:-------|:-----------|:-------------|:--------|
| **L1** | SymPy | `sympy` (pip) | ✅ Yes | Symbolic derivation & algebraic equivalence |
| **L2** | numpy | `numpy` (pip) | ✅ Yes | Numerical cross-check with random sampling |
| **L3** | pint | `pint` (pip) | ✅ Yes | Physical dimensional analysis |
| **L4** | Pure Python | — | ✅ Yes | Physical limit tests (far-field, near-field, symmetry) |
| **L5** | SymPy | `sympy` (pip) | ✅ Yes | Singularity detection (denominator zeros, branch cuts) |

**Key design decisions:**
- Layers L1–L3 are **fully independent** (different toolchains, same formula)
- L4 and L5 depend on **SymPy** (same engine as L1, different analysis angle)
- **No external API calls** needed — all verification runs locally
- **Graceful degradation**: missing `sympy` → L1/L5 skip; missing `pint` → L3 skip. Never crashes.

## Quick Start

```python
from hfpclawer.verify.registry import FormulaEntry, FormulaRegistry
from hfpclawer.verify.pipeline import VerificationPipeline

# 1. Create a registry
reg = FormulaRegistry("my_formulas.jsonl")

# 2. Add a formula
entry = FormulaEntry(
    fid="eq:biot-savart-segment",
    latex=r"B = \frac{\mu_0 I}{4\pi d} (\cos\alpha_2 - \cos\alpha_1) \hat{\phi}",
    sympy="mu0*I/(4*pi*d)*(cos(alpha2)-cos(alpha1))",
    pint_dimension="magnetic flux density",
    source_keys=["Griffiths2023"],
    tags=["magnetostatics", "biot-savart"],
)
reg.add(entry)
reg.save()

# 3. Verify
pipe = VerificationPipeline(registry=reg)
results = pipe.run_all()  # L1→L5 for all unverified entries
pipe.save_results("verify-results.json")
```

## Installation

The verify module installs as part of `hfpclawer`:

```bash
# Minimal — no extra dependencies needed
pip install hfpclawer

# With verify dependencies (recommended)
pip install "hfpclawer[verify]"   # Adds sympy, pint, numpy

# Or from source
cd hfpapers-crawler
pip install -e ".[verify]"
```

### Dependency Check

```python
import hfpclawer.verify as v
print(v.check_available())  
# Returns dict: {"sympy": True, "pint": True, "numpy": True}
```

## Formula Registry (JSONL Backend)

### Schema

```json
{
  "registry_schema_version": 1,
  "fid": "eq:biot-savart-segment",
  "latex": "B = \\frac{\\mu_0 I}{4\\pi d} (\\cos\\alpha_2 - \\cos\\alpha_1) \\hat{\\phi}",
  "sympy": "mu0*I/(4*pi*d)*(cos(alpha2)-cos(alpha1))",
  "source_keys": ["Griffiths2023"],
  "extracted_from": "sf:2501.01934",
  "equation_index": 15,
  "pint_dimension": "magnetic flux density",
  "verification_status": "unverified",
  "verified_at": null,
  "expires_at": null,
  "verifications": [],
  "tags": ["magnetostatics", "biot-savart"]
}
```

### Fields

| Field | Required | Description |
|:------|:---------|:------------|
| `fid` | ✅ | Unique formula ID (e.g. `eq:biot-savart-segment`) |
| `latex` | ✅ | LaTeX representation (canonical exchange format) |
| `sympy` | ❌ | SymPy expression string (needed for L1, L5) |
| `source_keys` | ❌ | Reference keys (e.g. `["Griffiths2023"]`) |
| `extracted_from` | ❌ | Paper `sf_id` this formula came from |
| `equation_index` | ❌ | Equation number in the source paper |
| `pint_dimension` | ❌ | Physical dimension key (see `dimensional.py`) |
| `tags` | ❌ | Category tags for query |

### Supported Dimension Keys

| Key | Unit | Physical quantity |
|:----|:-----|:-----------------|
| `magnetic flux density` | T | Tesla |
| `magnetic field strength` | A/m | H-field |
| `length` | m | Distance |
| `temperature` | K | Kelvin |
| `frequency` | Hz | Hertz |
| `electric current` | A | Ampere |
| `electric potential` | V | Volt |
| `energy` | J | Joule |
| `force` | N | Newton |
| `pressure` | Pa | Pascal |
| `velocity` | m/s | Speed |
| `acceleration` | m/s² | Acceleration |
| `area` | m² | Area |
| `volume` | m³ | Volume |
| `dimensionless` | — | Pure number |

### TTL (Time-To-Live)

Verified formulas expire after **365 days** by default. To change:

```python
from hfpclawer.verify.registry import FormulaRegistry, DEFAULT_EXPIRY_DAYS

# Per-entry override
entry.mark_verified("L1", "passed", ttl_days=180)  # 6 months

# Global default (modify source)
# hfpclawer/verify/registry.py: DEFAULT_EXPIRY_DAYS = 365
```

## Programming API

### Run Individual Layers

```python
from hfpclawer.verify.registry import FormulaRegistry
from hfpclawer.verify.pipeline import VerificationPipeline

reg = FormulaRegistry("my_formulas.jsonl")
pipe = VerificationPipeline(registry=reg)

entry = reg.get("eq:biot-savart-segment")

# Run specific layers
result_l1 = pipe.run_l1(entry)   # SymPy symbolic
result_l3 = pipe.run_l3(entry)   # pint dimensional

# Or all layers
all_results = pipe.verify_entry(entry)
```

### Layer Result Structure

```python
@dataclass
class LayerResult:
    fid: str          # Formula ID
    layer: str        # "L1"|"L2"|"L3"|"L4"|"L5"
    passed: bool      # True/False
    detail: str       # Human-readable explanation
    computed: float | None  # For L2 numerical checks
    expected: float | None  # For L2 numerical checks
    rel_error: float | None # Relative error for L2
```

### Registry Queries

```python
# All formulas
all_entries = reg.load_all()

# By status
unverified = reg.get_by_status("unverified")
verified = reg.get_by_status("verified")
failed = reg.get_by_status("failed")

# By tag
magnetostatic = reg.get_by_tag("magnetostatics")

# By source paper
from_paper = reg.get_by_source("sf:2501.01934")

# Only expired
expired = reg.get_expired()

# Statistics
stats = reg.stats()
# {"total": 42, "by_status": {"verified": 30, "unverified": 8, "failed": 4}, ...}
```

## CLI Usage (Future)

CLI commands for verify are planned for a future release. Currently, use Python scripts:

```bash
# Verify all unregistered formulas
python -c "
from hfpclawer.verify.pipeline import VerificationPipeline
from hfpclawer.verify.registry import FormulaRegistry
pipe = VerificationPipeline(registry_path='formula_registry.jsonl')
results = pipe.run_all()
print(f'Passed: {sum(1 for r in results if r.passed)}/{len(results)}')
"
```

---

# Optional Third-Party Services

The following services are **not required** for basic usage. They provide additional cross-validation for users who need the highest level of formula verification confidence.

---

## Wolfram Engine (Docker/Podman)

**Purpose:** L1 cross-validation — independently verify SymPy results using a second Computer Algebra System (CAS).

**Status:** 🟢 Implemented in external repos (`gsnv-theory`, `coc-inverse-agent`). Not yet integrated into `hfpclawer.verify` core. Integration planned for v0.8.x.

### Option A: Container (Recommended)

#### 1. Get a License

1. Go to https://www.wolfram.com/engine/free-license/
2. Create a free Wolfram ID (requires email)
3. Your free license key is emailed to you immediately
4. License terms: free for personal/development use; 1-year renewable

> **Practice date:** 2026-03-15 — free license obtained via wolfram.com/engine. Validated: license key works without account verification at endpoint. License renewal email arrives ~30 days before expiry.

#### 2. Pull & Run Container

```bash
# Pull the official image
docker pull wolframresearch/wolfram-engine:15.0.0

# Or via podman
podman pull docker.io/wolframresearch/wolfram-engine:15.0.0

# Run with license activation
docker run -it --rm -e WOLFRAM_LICENSE_KEY="xxxx-xxxx-xxxx-xxxx" \
  wolframresearch/wolfram-engine:15.0.0 wolframscript -code "Print[1+1]"
```

**Troubleshooting:**
- On first run, the container may prompt for Wolfram ID password. Pre-authenticate:
  ```bash
  docker run -it --rm wolframresearch/wolfram-engine:15.0.0 wolframscript -activate
  # Follow prompts to enter Wolfram ID email + password (not just license key)
  ```
- The activation is stored in the container; to persist, mount a volume:
  ```bash
  docker run -it --rm -v ~/.WolframEngine:/root/.WolframEngine \
    wolframresearch/wolfram-engine:15.0.0 wolframscript -code "..."
  ```

#### 3. Verify Installation

```bash
# Simple test
docker exec wolfram-engine wolframscript -code \
  'Print[TeXForm[Integrate[1/(x^2+z^2)^(3/2), {z, -Infinity, Infinity}]]]'
# Expected output: \frac{2}{x^2}

# Cross-check with SymPy
python -c "import sympy as sp; x=sp.symbols('x',positive=True); \
  print(sp.latex(sp.integrate(1/(x**2+z**2)**(3/2), (z, -sp.oo, sp.oo))))"
# Expected output: \frac{2}{x^{2}}
```

> **Practice date:** 2026-05-20 — Docker Wolfram Engine 15.0.0 validated on Ubuntu 22.04 host (i5-12450H). Memory usage: ~800 MB idle, ~1.5 GB during symbolic integration. Cold start: ~8 seconds.

### Option B: Native Installation (Linux)

```bash
# 1. Download the Wolfram Engine installer
wget https://account.wolfram.com/download/public/wolfram-engine/15.0.0/engine/WolframEngine_15.0.0_LINUX.sh

# 2. Run installer (needs ~2 GB disk space)
chmod +x WolframEngine_15.0.0_LINUX.sh
sudo ./WolframEngine_15.0.0_LINUX.sh

# 3. Activate
wolframscript -activate

# 4. Test
wolframscript -code 'Print[TeXForm[D[Sin[x]^2, x]]]'
# Expected: 2 \sin (x) \cos (x)
```

> **Practice date:** 2026-04-10 — Native Wolfram Engine 15.0.0 installed on Ubuntu 22.04. The installer uses a GUI wizard even with `--nox11` flag — the Docker route is simpler.

### Configuration in hfpclawer

```python
# Future config.yaml section (planned for v0.8.x)
verify:
  wolfram:
    method: docker          # "docker" | "podman" | "native" | "disabled"
    container: wolfram-engine
    timeout: 30             # Seconds
```

## Wolfram Alpha API

**Purpose:** L1 fallback for expressions that neither SymPy nor Wolfram Engine can handle natively (e.g., special functions, indefinite integrals of novel forms).

**Status:** 🟡 Not yet implemented in `hfpclawer.verify`. Planned for v0.8.x as optional L1b fallback.

### 1. Get an API Key

1. Register at https://products.wolframalpha.com/api/
2. Click "Get Started" → "Sign Up for Free"
3. Create a Wolfram ID (same as engine)
4. Select **Free Plan** (2,000 API calls/month)
5. Your App ID (API key) appears in the dashboard immediately

> **Practice date:** 2026-03-20 — Free tier app ID obtained at wolframalpha.com. API endpoint: `https://api.wolframalpha.com/v2/query`. Confirmed: 2,000 queries/month hard cap; resets monthly. No API key expiration observed after 3 months.

### 2. Rate Limits

| Plan | Monthly Limit | Rate Limit | Latency | Use When |
|:-----|:-------------|:-----------|:--------|:---------|
| 🆓 Free | 2,000 | ~1 req/s | ~2-5s | Development, spot-checking |
| 💼 Pro ($60/yr) | 10,000 | ~5 req/s | ~1-3s | Active research |
| 🏢 Enterprise | Custom | Custom | <1s | Production pipelines |

### 3. Python Client

```bash
pip install wolframalpha
```

```python
import wolframalpha
import os

# From .env or environment
client = wolframalpha.Client(os.environ["WOLFRAM_ALPHA_APP_ID"])

# Query
res = client.query("integrate 1/(x^2+z^2)^(3/2) dz from -inf to inf")

# Parse result
for pod in res.pods:
    if pod.title == "Indefinite integral":
        print(pod.text)
        # → (2 z)/(x^2 Sqrt[x^2+z^2])
```

### 4. Rate Limit Handling

```python
import time
import wolframalpha
from functools import lru_cache

class WolframAlphaClient:
    def __init__(self, app_id: str, monthly_budget: int = 2000):
        self.client = wolframalpha.Client(app_id)
        self.call_count = 0
        self.monthly_budget = monthly_budget
        self.last_call = 0.0
    
    @lru_cache(maxsize=128)
    def query(self, query_str: str) -> str | None:
        """Rate-limited Alpha query with monthly budget."""
        if self.call_count >= self.monthly_budget:
            logger.warning("Alpha API budget exhausted (%d/month)", self.monthly_budget)
            return None
        
        # Rate limit: 1 req/s
        elapsed = time.time() - self.last_call
        if elapsed < 1.0:
            time.sleep(1.0 - elapsed)
        
        try:
            res = self.client.query(query_str)
            self.call_count += 1
            self.last_call = time.time()
            return extract_result(res)
        except Exception as exc:
            logger.error("Alpha API error: %s", exc)
            return None
```

### 5. Configuration in hfpclawer

```python
# Future config.yaml section
verify:
  wolfram_alpha:
    enabled: false           # Disabled by default
    app_id_env: "WOLFRAM_ALPHA_APP_ID"
    monthly_budget: 500      # Conservative — only use for edge cases
```

## Lean 4 (Future L6)

**Purpose:** Formal theorem proving as the ultimate verification layer.

**Status:** 🔴 Not implemented. Reserved for L6 in future major versions.

**Documentation:** See `docs/formula-cross-validation-architecture.md` §10 for the Lean 4 design.

## Cost Summary

| Service | Cost | Limit | Use Case |
|:--------|:-----|:------|:---------|
| SymPy (L1, L5) | 🆓 Free | Unlimited | Symbolic derivation |
| numpy (L2) | 🆓 Free | Unlimited | Numerical cross-check |
| pint (L3) | 🆓 Free | Unlimited | Dimensional analysis |
| Wolfram Engine (Docker) | 🆓 Free* | 1-year license | CAS cross-validation |
| Wolfram Alpha API | 🆓 Free (2K/mo) | 2,000/month | Final cross-check |
| Lean 4 | 🆓 Free | Unlimited | Formal proof (future) |

*Wolfram Engine free license: personal/development use only, renewable annually.

## Comparison with Alternative CAS

| Engine | Installation | Speed | Coverage | License |
|:-------|:-------------|:------|:---------|:--------|
| SymPy | `pip install sympy` (instant) | Fast | Good for elementary functions | BSD (open) |
| Wolfram Engine | Docker ~2 GB pull | Medium | Excellent (special functions, diff eq) | Proprietary (free personal) |
| Wolfram Alpha | API only | Slow (2-5s) | Best (step-by-step) | Proprietary (free tier) |
| SageMath | `apt install sagemath` ~4 GB | Slow startup | Good (wraps SymPy + Maxima + Singular) | GPL (open) |
| Maxima | `apt install maxima` ~200 MB | Medium | Good for symbolic | GPL (open) |

**Recommendation:** Start with L1-SymPy only. Add Wolfram Engine if you encounter expressions that SymPy cannot handle (e.g., integrals involving special functions like `HypergeometricPFQ`, or piecewise integrals that SymPy returns unevaluated).

## FAQ

### Q: Do I need any API keys to use the verify module?

**No.** The verify module works entirely offline with no external API calls. Only L3 cross-validation (Wolfram) requires API keys or Docker — and it's completely optional.

### Q: My formulas are sensitive/proprietary. Can I verify them offline?

**Yes.** All L1–L5 layers run locally. No data leaves your machine.

### Q: Which layer catches unit conversion errors (μm → m)?

**L3 (pint)** catches dimension mismatches. **L4 (limit tests)** catches numerical order-of-magnitude errors by checking that results fall in physically reasonable ranges.

### Q: How do I verify a formula that doesn't have a SymPy expression?

L1 and L5 will skip gracefully. L3 (pint dimensional analysis) still works if you provide `pint_dimension`. L2 numeric checks can still run with hand-coded Python.

### Q: What happens if sympy or pint isn't installed?

Graceful degradation — missing engines are logged as warnings and skipped. The pipeline never crashes due to missing optional dependencies.
