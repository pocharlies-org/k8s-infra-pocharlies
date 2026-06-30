import crypto from 'node:crypto';
import net from 'node:net';
import tls from 'node:tls';

const url = new URL(process.env.OPENCLAW_LAN_HEALTHCHECK_URL || 'wss://openclaw.lan.e-dani.com/');
const origin = process.env.OPENCLAW_LAN_HEALTHCHECK_ORIGIN || 'https://openclaw.lan.e-dani.com';
const timeoutMs = Number(process.env.OPENCLAW_LAN_HEALTHCHECK_TIMEOUT_MS || '8000');
const expectedEvent = process.env.OPENCLAW_LAN_HEALTHCHECK_EXPECTED || 'connect.challenge';
const port = Number(url.port || (url.protocol === 'wss:' ? '443' : '80'));
const hostHeader = url.host;
const key = crypto.randomBytes(16).toString('base64');
const expectedAccept = crypto
  .createHash('sha1')
  .update(`${key}258EAFA5-E914-47DA-95CA-C5AB0DC85B11`)
  .digest('base64');

function fail(message) {
  console.error(`[openclaw-lan-healthcheck] FAIL ${message}`);
  process.exit(1);
}

function pass(message) {
  console.log(`[openclaw-lan-healthcheck] PASS ${message}`);
  process.exit(0);
}

const socket = url.protocol === 'wss:'
  ? tls.connect({ host: url.hostname, port, servername: url.hostname })
  : net.connect({ host: url.hostname, port });

let buffer = Buffer.alloc(0);
let headerParsed = false;

const timer = setTimeout(() => {
  socket.destroy();
  fail(`timeout after ${timeoutMs}ms url=${url.href}`);
}, timeoutMs);

socket.on('error', (error) => {
  clearTimeout(timer);
  fail(`socket error url=${url.href}: ${error.message}`);
});

socket.on('connect', () => {
  const path = `${url.pathname || '/'}${url.search}`;
  socket.write([
    `GET ${path} HTTP/1.1`,
    `Host: ${hostHeader}`,
    'Upgrade: websocket',
    'Connection: Upgrade',
    `Sec-WebSocket-Key: ${key}`,
    'Sec-WebSocket-Version: 13',
    `Origin: ${origin}`,
    'User-Agent: openclaw-lan-websocket-healthcheck/1',
    '',
    '',
  ].join('\r\n'));
});

socket.on('data', (chunk) => {
  buffer = Buffer.concat([buffer, chunk]);

  if (!headerParsed) {
    const headerEnd = buffer.indexOf(Buffer.from('\r\n\r\n'));
    if (headerEnd < 0) return;

    const header = buffer.subarray(0, headerEnd).toString('latin1');
    const lines = header.split('\r\n');
    const statusLine = lines[0] || '';
    if (!/^HTTP\/1\.[01] 101\b/.test(statusLine)) {
      clearTimeout(timer);
      socket.destroy();
      fail(`unexpected handshake status: ${statusLine}`);
    }

    const acceptHeader = lines.find((line) => /^sec-websocket-accept:/i.test(line));
    const acceptValue = acceptHeader?.split(':').slice(1).join(':').trim();
    if (acceptValue !== expectedAccept) {
      clearTimeout(timer);
      socket.destroy();
      fail('invalid Sec-WebSocket-Accept header');
    }

    headerParsed = true;
    buffer = buffer.subarray(headerEnd + 4);
  }

  if (buffer.includes(Buffer.from(expectedEvent))) {
    clearTimeout(timer);
    socket.end();
    pass(`${url.href} emitted ${expectedEvent}`);
  }
});

socket.on('end', () => {
  if (!headerParsed) {
    clearTimeout(timer);
    fail('socket ended before WebSocket handshake completed');
  }
});
