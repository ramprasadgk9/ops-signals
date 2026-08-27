export type LabPassFailStatus = 'pass' | 'fail' | 'unknown';

function formatScalar(value: unknown): string {
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  if (value === null || value === undefined) return 'null';
  const text = String(value);
  return /^[a-zA-Z0-9_.-]+$/.test(text) ? text : JSON.stringify(text);
}

function appendYaml(lines: string[], value: unknown, indent: number) {
  if (Array.isArray(value)) {
    for (const item of value) {
      if (item && typeof item === 'object') {
        lines.push(`${' '.repeat(indent)}-`);
        appendYaml(lines, item, indent + 2);
      } else {
        lines.push(`${' '.repeat(indent)}- ${formatScalar(item)}`);
      }
    }
    return;
  }
  if (value && typeof value === 'object') {
    for (const [key, child] of Object.entries(value as Record<string, unknown>)) {
      if (child && typeof child === 'object') {
        lines.push(`${' '.repeat(indent)}${key}:`);
        appendYaml(lines, child, indent + 2);
      } else {
        lines.push(`${' '.repeat(indent)}${key}: ${formatScalar(child)}`);
      }
    }
  }
}

export function analyzerConfigYaml(analyzerId: string, block: Record<string, unknown>) {
  const lines = [`${analyzerId}:`];
  appendYaml(lines, block, 2);
  return `${lines.join('\n')}\n`;
}

export function downloadText(filename: string, text: string) {
  const blob = new Blob([text], { type: 'text/yaml;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export function passFailFromFinding(shouldFind: boolean, didFind: boolean): LabPassFailStatus {
  return shouldFind === didFind ? 'pass' : 'fail';
}
