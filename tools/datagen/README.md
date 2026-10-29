# Synthetic Test Data Generator (Lane F)

This package deterministically generates synthetic invoice documents with exact ground truth labels and manifest metadata conforming to `docs/CONTRACTS.md` (Sections 7 and 10).

## Environment Setup

The generator runs in an isolated virtual environment at `tools/datagen/.venv`:

```powershell
# Create virtual environment (Python 3.12 / host Python)
python -m venv tools/datagen/.venv

# Activate virtual environment
.\tools\datagen\.venv\Scripts\Activate.ps1

# Install lightweight dependencies
pip install -r tools/datagen/requirements.txt
```

## Dataset Generation

Run the generator with a fixed random seed (default: `42`):

```powershell
.\tools\datagen\.venv\Scripts\python.exe tools/datagen/generate.py
```

### Determinism & Byte-Identical Reruns
- Uses fixed random seed (`42`).
- ReportLab is configured in invariant mode (`reportlab.rl_config.invariant = 1`) to ensure PDF binaries, metadata timestamps, and object streams are byte-identical across runs.
- JSON labels and `data/manifest.csv` are sorted deterministically with explicit newline handling.
- Running the generation command twice yields 100% byte-identical files.

## Dataset Verification

Run the self-check verification script:

```powershell
.\tools\datagen\.venv\Scripts\python.exe tools/datagen/verify.py
```

`verify.py` validates:
- Manifest structure and column names per CONTRACTS Section 10.
- Sample file presence, non-zero file sizes, and valid magic bytes (`%PDF-`).
- Label JSON integrity and schema per CONTRACTS Sections 7 and 10.
- Strict decimal string types for all monetary amounts (no floating point numbers).
- ISO `YYYY-MM-DD` date formatting.
- Strict disjointness between dev and test layouts and suppliers (0 overlap).
- Summary distributions by kind, quality, split, and expected status.

## Layouts & Split Distribution

### Layouts
- **Dev Layouts (4)**: `modern_clean`, `classic_corporate`, `compact_slip`, `bold_banner`
- **Test Layouts (2)**: `minimalist_sidebar`, `international_multilingual`

### Suppliers
- **Dev Suppliers (11)**: 11 distinct fake companies across USD, EUR, GBP, BDT.
- **Test Suppliers (5)**: 5 distinct fake companies across USD, GBP, EUR, JPY, INR.

There is 0 overlap between dev and test layouts, and 0 overlap between dev and test suppliers.
