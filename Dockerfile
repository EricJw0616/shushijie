FROM python:3.11-slim-bookworm

ARG DEBIAN_MIRROR=https://deb.debian.org/debian
ARG DEBIAN_SECURITY_MIRROR=https://deb.debian.org/debian-security
ARG PIP_INDEX_URL=https://pypi.org/simple

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    BOOKDISTILL_ROOT=/app \
    BOOKDISTILL_OCR_PYTHON=/usr/local/bin/python \
    TZ=Asia/Shanghai

RUN python -c "import os,pathlib; p=pathlib.Path('/etc/apt/sources.list.d/debian.sources'); s=p.read_text(); s=s.replace('http://deb.debian.org/debian-security',os.environ['DEBIAN_SECURITY_MIRROR']).replace('http://deb.debian.org/debian',os.environ['DEBIAN_MIRROR']); p.write_text(s)" \
    && apt-get -o Acquire::Retries=3 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 update \
    && apt-get install -y --no-install-recommends gosu libgl1 libglib2.0-0 libgomp1 tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 bookworld \
    && useradd --uid 10001 --gid bookworld --create-home bookworld

WORKDIR /app
COPY app/requirements.txt /tmp/app-requirements.txt
COPY platform/engine/requirements-ocr.txt /tmp/ocr-requirements.txt
COPY requirements-pg.txt /tmp/pg-requirements.txt
# This override changes only the Python dependency layer, keeping the OS cache.
ARG PIP_INSTALL_INDEX_URL=
RUN pip install --index-url "${PIP_INSTALL_INDEX_URL:-$PIP_INDEX_URL}" --no-cache-dir -r /tmp/app-requirements.txt -r /tmp/ocr-requirements.txt -r /tmp/pg-requirements.txt \
    && python -c "from rapidocr_onnxruntime import RapidOCR; RapidOCR()" \
    && rm -f /tmp/*-requirements.txt

COPY --chown=10001:10001 app /app/app
COPY --chown=10001:10001 platform/engine /app/platform/engine
COPY --chown=10001:10001 platform/config /opt/bookworld-defaults/config
COPY --chown=10001:10001 lexicon /opt/bookworld-defaults/lexicon
COPY --chown=10001:10001 .workbuddy/skills /app/.workbuddy/skills
COPY --chown=10001:10001 *.md /app/
COPY deploy/entrypoint.sh /usr/local/bin/bookworld-entrypoint
COPY deploy/healthcheck.py /usr/local/bin/bookworld-healthcheck.py
RUN chmod 755 /usr/local/bin/bookworld-entrypoint \
    && mkdir -p /app/app/data /app/platform/out /app/platform/library /app/platform/config /app/lexicon /app/书库分类 \
    && chown -R 10001:10001 /app/platform /app/lexicon /app/书库分类 \
    && python app/run.py --check

EXPOSE 8943
ENTRYPOINT ["bookworld-entrypoint"]
CMD ["python", "-u", "app/run.py", "--host", "0.0.0.0", "--port", "8943"]
