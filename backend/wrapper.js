const { spawn } = require('child_process');
const http = require('http');
const path = require('path');
const fs = require('fs');
const httpProxy = require('http-proxy');

const isWindows = process.platform === 'win32';
const internalPort = 8001;
const publicPort = process.env.PORT || 8000;

console.log('Starting Node process supervisor and wrapper...');

// Prepare child environment
const childEnv = { ...process.env, PORT: String(internalPort) };

// Ensure BASE_URL is set correctly if not specified
if (!process.env.BASE_URL) {
    childEnv.BASE_URL = `http://localhost:${publicPort}`;
}

// Prepend venv bin folder to PATH if present (useful for local development)
const venvPath = path.join(__dirname, 'venv');
if (fs.existsSync(venvPath)) {
    const venvBin = isWindows 
        ? path.join(venvPath, 'Scripts') 
        : path.join(venvPath, 'bin');
    const pathSeparator = isWindows ? ';' : ':';
    childEnv.PATH = `${venvBin}${pathSeparator}${childEnv.PATH || ''}`;
}

// Spawn the Python FastAPI app using uvicorn
console.log(`Spawning Python process (uvicorn main:app --host 127.0.0.1 --port ${internalPort})...`);
const pythonProcess = spawn('uvicorn', ['main:app', '--host', '127.0.0.1', '--port', String(internalPort)], {
    stdio: 'inherit',
    shell: isWindows,
    env: childEnv
});

// Exit helper
const handlePythonExit = (code, signal) => {
    console.log(`Python process exited. Code: ${code}, Signal: ${signal}`);
    process.exit(code !== null ? code : 1);
};

pythonProcess.on('exit', handlePythonExit);
pythonProcess.on('close', handlePythonExit);
pythonProcess.on('error', (err) => {
    console.error('Failed to spawn Python process:', err);
    process.exit(1);
});

// Signal forwarding for graceful shutdown
const forwardSignal = (signal) => {
    if (pythonProcess && !pythonProcess.killed) {
        try {
            pythonProcess.kill(signal);
        } catch (e) {
            console.error(`Error killing python process with signal ${signal}:`, e);
        }
    }
};

process.on('SIGTERM', () => {
    console.log('Node supervisor received SIGTERM, forwarding to Python...');
    forwardSignal('SIGTERM');
});

process.on('SIGINT', () => {
    console.log('Node supervisor received SIGINT, forwarding to Python...');
    forwardSignal('SIGINT');
});

// Poll the Python server until it's ready
const pollUrl = `http://127.0.0.1:${internalPort}/`;
const pollTimeout = 30000; // 30 seconds
const pollInterval = 250;  // 250ms

console.log(`Waiting for Python app to be ready on ${pollUrl}...`);

const pollStartTime = Date.now();
const pollIntervalId = setInterval(() => {
    if (Date.now() - pollStartTime > pollTimeout) {
        clearInterval(pollIntervalId);
        console.error('Timeout waiting for Python app to start.');
        forwardSignal('SIGTERM');
        process.exit(1);
    }

    const req = http.get(pollUrl, (res) => {
        // Any response (even 404) means the server is running and responding
        clearInterval(pollIntervalId);
        console.log(`Python app is ready. Starting reverse proxy on port ${publicPort}...`);
        startProxy();
    });

    req.on('error', (err) => {
        // Ignore error and retry on the next interval
    });

    req.end();
}, pollInterval);

// Start the HTTP reverse proxy
function startProxy() {
    const proxy = httpProxy.createProxyServer({});

    proxy.on('error', (err, req, res) => {
        console.error('Proxy error:', err);
        if (!res.headersSent) {
            res.writeHead(502, { 'Content-Type': 'text/plain' });
            res.end('Bad Gateway');
        }
    });

    const server = http.createServer((req, res) => {
        proxy.web(req, res, { target: `http://127.0.0.1:${internalPort}` });
    });

    server.listen(publicPort, () => {
        console.log(`Reverse proxy listening on port ${publicPort}`);
    });
}
