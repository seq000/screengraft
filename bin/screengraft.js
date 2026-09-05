#!/usr/bin/env node
/*
 * screengraft — launcher.
 *
 * This package is a delivery mechanism, not a JavaScript library. The tool is
 * Python and OpenCV; npm is here because `npx screengraft` is the shortest path
 * from "I have a photo" to a fitting page, with nothing installed permanently.
 * It says so out loud rather than pretending otherwise, and it never installs
 * anything behind your back: if the Python side is missing you get the exact
 * command to run, and a non-zero exit.
 */
'use strict';

const { spawn, spawnSync } = require('node:child_process');
const path = require('node:path');
const process = require('node:process');

const ROOT = path.join(__dirname, '..');
const PREFLIGHT = path.join(ROOT, 'scripts', 'preflight.py');
const UI = path.join(ROOT, 'scripts', 'ui.py');

const argv = process.argv.slice(2);
if (argv.includes('-h') || argv.includes('--help')) {
  process.stdout.write(
    'screengraft — put a UI screenshot onto a photographed device screen.\n\n' +
    'Usage:  npx screengraft [--out-dir DIR] [--port N] [--no-open]\n\n' +
    '  --out-dir DIR   where Save writes (default ~/Desktop/screengraft)\n' +
    '  --port N        0 picks a free port (default)\n' +
    '  --no-open       do not open a browser tab\n' +
    '  --install       build the Python venv this needs, then exit\n\n' +
    'Needs python3 with OpenCV and numpy. The first run offers to build an\n' +
    'isolated venv at ~/.screengraft/venv (~60 MB); your system Python is left\n' +
    'alone. Docs: https://github.com/seq000/screengraft\n');
  process.exit(0);
}

function python() {
  for (const exe of ['python3', 'python']) {
    const r = spawnSync(exe, ['--version'], { stdio: 'ignore' });
    if (!r.error && r.status === 0) return exe;
  }
  return null;
}

const py = python();
if (!py) {
  process.stderr.write(
    'screengraft needs python3, and none was found on PATH.\n' +
    'Install Python 3.10 or newer, then run this again.\n');
  process.exit(1);
}

if (argv.includes('--install')) {
  process.exit(spawnSync(py, [PREFLIGHT, '--install'], { stdio: 'inherit' }).status ?? 1);
}

// Preflight reports which interpreter actually has OpenCV — the venv's, usually,
// not the one running this check.
const pre = spawnSync(py, [PREFLIGHT], { encoding: 'utf8' });
let report;
try {
  report = JSON.parse(pre.stdout);
} catch {
  process.stderr.write('screengraft: preflight did not report cleanly.\n' + (pre.stderr || pre.stdout || ''));
  process.exit(1);
}

if (!report.ready) {
  process.stderr.write(
    'screengraft needs OpenCV, and it is not installed.\n\n' +
    'OpenCV is the engine here, not an enhancement: without it there is no\n' +
    'degraded mode, there is no mode. Missing: ' + (report.missing || []).join(', ') + '\n\n' +
    'To build an isolated venv at ~/.screengraft/venv (about 60 MB, and it\n' +
    'touches nothing else on your machine):\n\n' +
    '    npx screengraft --install\n\n');
  process.exit(1);
}

// report.python is the interpreter that has the engine.
const child = spawn(report.python, [UI, ...argv], { stdio: 'inherit' });
child.on('exit', (code, signal) => process.exit(signal ? 1 : (code ?? 0)));
for (const sig of ['SIGINT', 'SIGTERM']) process.on(sig, () => child.kill(sig));
