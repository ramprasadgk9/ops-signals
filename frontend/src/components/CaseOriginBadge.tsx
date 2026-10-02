import { Chip, Link } from '@mui/material';

/** Marks a case imported from an incident tool or postmortem, linking back to the original when
 * the import carried a URL. Detected cases render nothing. */
export function CaseOriginBadge({ source, sourceId, sourceUrl }: { source?: string | null; sourceId?: string | null; sourceUrl?: string | null }) {
  if (!source || source === 'detected') return null;
  const label = `Imported · ${source}${sourceId && !sourceId.startsWith('fp-') ? ` ${sourceId}` : ''}`;
  const chip = <Chip size="small" variant="outlined" color="secondary" label={label} sx={{ fontWeight: 800 }} />;
  if (!sourceUrl) return chip;
  return (
    <Link href={sourceUrl} target="_blank" rel="noreferrer" underline="none" onClick={(event) => event.stopPropagation()}>
      {chip}
    </Link>
  );
}
