FROM python:3.11-slim

# Install ffmpeg + Node.js (needed for hanime.tv WASM signature generation)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Make N_m3u8DL-RE executable
RUN chmod +x binary/N_m3u8DL-RE

CMD ["python", "app.py"]
