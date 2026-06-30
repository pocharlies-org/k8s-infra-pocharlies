import net from 'node:net';

const listenHost = process.env.OPENCLAW_PROXY_LISTEN_HOST || '100.109.183.9';
const listenPort = Number(process.env.OPENCLAW_PROXY_LISTEN_PORT || '18789');
const targetHost = process.env.OPENCLAW_PROXY_TARGET_HOST || '127.0.0.1';
const targetPort = Number(process.env.OPENCLAW_PROXY_TARGET_PORT || '18789');
const rewriteHost = process.env.OPENCLAW_PROXY_REWRITE_HOST || `${targetHost}:${targetPort}`;
const maxInitialBytes = Number(process.env.OPENCLAW_PROXY_MAX_INITIAL_BYTES || `${64 * 1024}`);
const allowed = new Set((process.env.OPENCLAW_PROXY_ALLOWED_IPS || '100.83.56.98')
  .split(',')
  .map((value) => value.trim())
  .filter(Boolean));

function normalizeAddress(address) {
  if (!address) return '';
  return address.startsWith('::ffff:') ? address.slice(7) : address;
}

function rewriteInitialRequest(buffer) {
  const marker = Buffer.from('\r\n\r\n');
  const headerEnd = buffer.indexOf(marker);
  if (headerEnd < 0) return null;

  const header = buffer.subarray(0, headerEnd + marker.length).toString('latin1');
  const rest = buffer.subarray(headerEnd + marker.length);
  const nextHeader = `\r\nHost: ${rewriteHost}`;
  const rewritten = /\r\nHost:[^\r\n]*/i.test(header)
    ? header.replace(/\r\nHost:[^\r\n]*/i, nextHeader)
    : header.replace(/\r\n/, `${nextHeader}\r\n`);

  return Buffer.concat([Buffer.from(rewritten, 'latin1'), rest]);
}

const server = net.createServer((client) => {
  const remote = normalizeAddress(client.remoteAddress);
  if (!allowed.has(remote)) {
    console.warn(`[openclaw-lan-proxy] rejected remote=${remote || 'unknown'}`);
    client.destroy();
    return;
  }

  const upstream = net.connect({ host: targetHost, port: targetPort });
  let initialChunks = [];
  let initialBytes = 0;
  let forwardedInitial = false;

  const closeBoth = () => {
    client.destroy();
    upstream.destroy();
  };

  const forwardInitial = (chunk) => {
    if (forwardedInitial) {
      upstream.write(chunk);
      return;
    }

    initialChunks.push(chunk);
    initialBytes += chunk.length;
    if (initialBytes > maxInitialBytes) {
      console.warn(`[openclaw-lan-proxy] initial request too large remote=${remote}`);
      closeBoth();
      return;
    }

    const buffered = Buffer.concat(initialChunks, initialBytes);
    const rewritten = rewriteInitialRequest(buffered);
    if (!rewritten) return;

    forwardedInitial = true;
    initialChunks = [];
    initialBytes = 0;
    upstream.write(rewritten);
    client.removeListener('data', forwardInitial);
    client.pipe(upstream);
  };

  upstream.on('error', (error) => {
    console.warn(`[openclaw-lan-proxy] upstream error remote=${remote}: ${error.message}`);
    closeBoth();
  });
  client.on('error', () => closeBoth());
  client.on('close', () => upstream.destroy());
  upstream.on('close', () => client.destroy());
  client.on('data', forwardInitial);
  upstream.pipe(client);
});

server.on('error', (error) => {
  console.error(`[openclaw-lan-proxy] listen error: ${error.message}`);
  process.exit(1);
});

server.listen(listenPort, listenHost, () => {
  console.log(`[openclaw-lan-proxy] listening ${listenHost}:${listenPort} -> ${targetHost}:${targetPort}; allowed=${[...allowed].join(',')}; rewriteHost=${rewriteHost}`);
});
