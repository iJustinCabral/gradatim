FROM python:3.11-slim

# No external dependencies — just Python stdlib
# No pip install needed

WORKDIR /app

COPY gradatim/ ./gradatim/
COPY tests/ ./tests/

# Run as non-root user
RUN useradd -m -r gradatim
USER gradatim

# Agent network ports (UDP) + web server port (TCP)
EXPOSE 8080 9001/udp 9002/udp 9003/udp

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import http.client; c=http.client.HTTPConnection('127.0.0.1',8080); c.request('GET','/healthz'); r=c.getresponse(); exit(0 if r.status==200 else 1)"

ENV GRADATIM_HOST=0.0.0.0
ENV GRADATIM_PORT=8080

CMD ["python", "-m", "gradatim", "web", "--host", "0.0.0.0", "--port", "8080"]
