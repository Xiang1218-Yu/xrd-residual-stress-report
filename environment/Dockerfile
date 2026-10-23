FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1

# Harbor starts the agent as this unprivileged account.  The verifier remains
# root so its mounted tests and /logs/verifier reward are outside agent control.
RUN addgroup --gid 10001 agent \
 && adduser --uid 10001 --gid 10001 --disabled-password --gecos '' agent \
 && install -d -o agent -g agent -m 0755 /app

WORKDIR /app
COPY --chown=agent:agent xrd_stress_report.py /app/xrd_stress_report.py

RUN python3 -m py_compile /app/xrd_stress_report.py

CMD ["python3", "-c", "import time; time.sleep(10**9)"]
