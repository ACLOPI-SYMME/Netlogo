# Agent service (Línea A): python -m aclopi.agent. No NetLogo / JVM: it talks to the platform over HTTP.
FROM python:3.12-slim
WORKDIR /app
COPY requirements-agent.txt .
RUN pip install --no-cache-dir -r requirements-agent.txt
COPY aclopi ./aclopi
ENV PYTHONUNBUFFERED=1 ACLOPI_AGENT_PORT=8100
EXPOSE 8100
CMD ["python", "-m", "aclopi.agent"]
