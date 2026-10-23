import { Chip, Tooltip } from '@mui/material';

/** "Found automatically" after a What changed line whose deploy Ops Signals found in Prometheus
 * rather than CI sending it (docs/deploy-discovery.md). `hint` comes from foundChangeHint. */
export function FoundDeployTag({ hint }: { hint: string }) {
  return (
    <Tooltip title={hint} arrow>
      <Chip
        label="Found automatically"
        size="small"
        color="success"
        variant="outlined"
        tabIndex={0}
        aria-label={`Found automatically. ${hint}`}
        sx={{ height: 20, fontSize: '0.7rem', ml: 0.75, verticalAlign: 'middle' }}
      />
    </Tooltip>
  );
}
