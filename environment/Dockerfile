FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
WORKDIR /app
COPY xrd_stress_report.py /app/xrd_stress_report.py
RUN python3 -m pip install --no-cache-dir pytest==8.3.5 \
    && python3 -m py_compile /app/xrd_stress_report.py
CMD ["python3", "-c", "import time; time.sleep(10**9)"]