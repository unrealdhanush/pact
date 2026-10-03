import { cp, mkdir, readFile, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = fileURLToPath(new URL('../', import.meta.url));
const output = path.join(root, 'dist');
await mkdir(output, { recursive: true });
await cp(path.join(root, 'web/index.html'), path.join(output, 'index.html'));
await cp(path.join(root, 'web/assets'), path.join(output, 'assets'), { recursive: true });
// The hosted presentation should open the hosted product, on the same domain.
const keynote = path.join(output, 'assets/pact-keynote.html');
await writeFile(keynote, (await readFile(keynote, 'utf8')).replaceAll('http://127.0.0.1:8017/#workspace', '/#workspace'));
console.log('Pact frontend, film, and presentation are ready in dist/.');
