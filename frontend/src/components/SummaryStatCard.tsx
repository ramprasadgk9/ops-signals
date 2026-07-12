import { Card, CardContent, Typography } from '@mui/material';

type Props = {
  label: string;
  value: string | number;
};

export function SummaryStatCard({ label, value }: Props) {
  return (
    <Card>
      <CardContent>
        <Typography variant="body2" color="text.secondary">{label}</Typography>
        <Typography variant="h5">{value}</Typography>
      </CardContent>
    </Card>
  );
}
