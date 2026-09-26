import { Box, Button, Card, CardContent, Stack, Typography } from '@mui/material';
import { Link as RouterLink } from 'react-router-dom';

export function SettingsPage() {
  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
      <Box>
        <Typography variant="h4" sx={{ mb: 1 }}>Settings</Typography>
        <Typography variant="body2" color="text.secondary">
          Configure platform behavior and preferences.
        </Typography>
      </Box>

      <Card>
        <CardContent>
          <Typography variant="h6" sx={{ mb: 2 }}>Analysis Configuration</Typography>
          <Stack spacing={2}>
            <Box>
              <Typography variant="subtitle2">Provider Settings</Typography>
              <Typography variant="body2" color="text.secondary">
                Configure data providers and ingestion sources.
              </Typography>
            </Box>
            <Box>
              <Typography variant="subtitle2">Capability Settings</Typography>
              <Typography variant="body2" color="text.secondary">
                Enable or disable analysis capabilities and configure their parameters.
              </Typography>
            </Box>
          </Stack>
        </CardContent>
      </Card>

      <Card>
        <CardContent>
          <Typography variant="h6" sx={{ mb: 1 }}>Data Sources</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
            OTLP metrics, Alertmanager alerts, Prometheus and CSV uploads are set up and monitored on the Integrations page.
          </Typography>
          <Button component={RouterLink} to="/integrations" variant="outlined" size="small" sx={{ textTransform: 'none' }}>
            Open Integrations
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardContent>
          <Typography variant="h6" sx={{ mb: 2 }}>Display Preferences</Typography>
          <Stack spacing={2}>
            <Box>
              <Typography variant="subtitle2">Theme</Typography>
              <Typography variant="body2" color="text.secondary">
                Switch between light and dark mode in the top navigation.
              </Typography>
            </Box>
          </Stack>
        </CardContent>
      </Card>
    </Box>
  );
}
