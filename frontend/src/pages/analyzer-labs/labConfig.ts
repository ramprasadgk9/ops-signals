export type LabPassFailStatus = 'pass' | 'fail' | 'unknown';

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
