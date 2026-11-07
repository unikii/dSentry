FROM python:3.12-slim

WORKDIR /hub

COPY hub/api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy only runtime files. The build context is the repository root, so
# copying hub/api/ wholesale would bake local SQLite databases, .env files,
# and other runtime state into the image.
COPY hub/api/app ./app
COPY hub/api/manage_users.py ./manage_users.py
COPY schemas/ /hub/schemas/
COPY LICENSE NOTICE /usr/share/doc/dsentry/

# Run unprivileged. The bind-mounted /data directory must be writable by this
# UID (see README: `chown -R 10001:10001 data`).
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin dsentry \
    && mkdir -p /data \
    && chown dsentry:dsentry /data
USER dsentry

EXPOSE 9090

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9090"]
