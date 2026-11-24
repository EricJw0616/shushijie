FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    BOOKDISTILL_ROOT=/app \
    BOOKDISTILL_OCR_PYTHON=/usr/local/bin/python \
    TZ=Asia/Shanghai

RUN apt-get update \
    && apt-get install -y --no-install-recommends gosu libgl1 libglib2.0-0 libgomp1 tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 bookworld \
    && useradd --uid 10001 --gid bookworld --create-home bookworld

WORKDIR /app
COPY app/requirements.txt /tmp/app-requirements.txt
COPY platform/engine/requirements-ocr.txt /tmp/ocr-requirements.txt
COPY requirements-pg.txt /tmp/pg-requirements.txt
RUN pip install --no-cache-dir -r /tmp/app-requirements.txt -r /tmp/ocr-requirements.txt -r /tmp/pg-requirements.txt \
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
