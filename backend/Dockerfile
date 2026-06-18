FROM python:3.10-slim

RUN apt-get update && apt-get install -y ffmpeg curl unzip nodejs npm && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local sh
ENV PATH="/usr/local/bin:${PATH}"

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Node.js dependencies
COPY package.json .
RUN npm install --only=production

# Copy source code
COPY . .

EXPOSE 8000

CMD ["node", "wrapper.js"]
