import { Chip, Stack } from '@mui/material';

type Props = {
  start: string;
  end: string;
};

export function AnalysisWindowSelector({ start, end }: Props) {
  return (
    <Stack direction="row" spacing={1}>
      <Chip label={`Start: ${new Date(start).toLocaleString()}`} />
      <Chip label={`End: ${new Date(end).toLocaleString()}`} />
    </Stack>
  );
}
