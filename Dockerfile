# Nashr: single-stage image bundling Python 3.13 + Node.js 22.
#
# The Python bot, FastAPI surface, and article worker all run from this
# image; the Node-based presentation worker also lives here (it's a
# subprocess invoked by the orchestrator). We keep everything in one
# image rather than splitting Python and Node into separate services so
# the presentation pipeline can call ``npm run`` against the renderer
# without a network hop.

FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# System dependencies:
#   - curl       : healthcheck + Node install
#   - poppler    : PyMuPDF helpers / PDF rasterisation
#   - tesseract  : OCR fallback for scanned PDFs (uz + ru language packs)
#   - libreoffice-writer : DOCX -> PDF in the article pipeline
#   - ca-certificates    : TLS to Supabase / R2 / LLM providers
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        poppler-utils \
        tesseract-ocr \
        tesseract-ocr-uzb \
        tesseract-ocr-rus \
        libreoffice-writer \
        libreoffice-impress \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Fonts the Design Direction Pass can emit (R50 diacritic-safe set).
# apt for the reliable ones; the four apt lacks are vendored in fonts/.
# Installed so Chromium renders the REQUESTED font (fallbacks also break
# text measurement via wrong glyph widths).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        fonts-inter \
        fonts-noto-core \
        fonts-noto-extra \
        fonts-ebgaramond \
        fonts-jetbrains-mono \
    && rm -rf /var/lib/apt/lists/*
COPY fonts/ /usr/share/fonts/truetype/nashr/
RUN fc-cache -f

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Node worker deps + Playwright Chromium.
COPY packages/presentation-worker/package.json packages/presentation-worker/package-lock.json* ./packages/presentation-worker/
RUN cd packages/presentation-worker \
    && (test -f package-lock.json && npm ci || npm install) \
    && npx playwright install --with-deps chromium

# Now copy the rest of the source and build the Node worker once.
COPY . .
RUN cd packages/presentation-worker && npm run build

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -fsS http://localhost:8080/health || exit 1

CMD ["python", "-m", "packages.bot.run", "--webhook"]
