/**
 * Executable entry point for the Python service. Reads one JSON request on
 * stdin and writes one JSON envelope on stdout so the caller never has to
 * parse partial or interleaved output.
 */
import { runBridge, type BridgeRequest } from './cli.js';

async function readStdin(): Promise<string> {
  const chunks: Buffer[] = [];
  for await (const chunk of process.stdin) chunks.push(chunk as Buffer);
  return Buffer.concat(chunks).toString('utf8');
}

async function main(): Promise<void> {
  try {
    const request = JSON.parse(await readStdin()) as BridgeRequest;
    process.stdout.write(JSON.stringify({ ok: true, result: runBridge(request) }));
  } catch (error) {
    process.stdout.write(
      JSON.stringify({ ok: false, error: error instanceof Error ? error.message : String(error) }),
    );
    process.exitCode = 1;
  }
}

void main();
