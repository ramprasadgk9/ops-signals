import { Box, Table, TableBody, TableCell, TableHead, TableRow, Typography } from '@mui/material';
import type { FindingCustomSettings } from '../types';
import { settingValue } from '../utils/customSettings';

/** "Found with custom settings": each setting a per-service override changed for this finding, the
 * value used next to the default, and who set it and why. */
export function CustomSettingsBox({ custom }: { custom: FindingCustomSettings }) {
  const files = [...new Set(custom.overrides.map((override) => override.file).filter(Boolean))];
  return (
    <Box data-testid="finding-custom-settings-box" sx={{ mb: 3, p: 2, borderRadius: 1, border: 1, borderColor: 'secondary.main', bgcolor: 'rgba(124, 58, 237, 0.06)' }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 2, flexWrap: 'wrap' }}>
        <Typography sx={{ fontWeight: 800, color: 'secondary.main' }}>Found with custom settings</Typography>
        {files.length ? <Typography variant="caption" color="text.secondary">{files.join(', ')}</Typography> : null}
      </Box>
      <Table size="small" sx={{ mt: 1 }}>
        <TableHead>
          <TableRow>
            <TableCell>Setting</TableCell>
            <TableCell>Here</TableCell>
            <TableCell>Default</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {custom.settings.map((setting) => (
            <TableRow key={`${setting.analyzer_id}.${setting.path}`}>
              <TableCell>{setting.analyzer}: {setting.label}</TableCell>
              <TableCell sx={{ fontWeight: 800 }}>{settingValue(setting.value)}</TableCell>
              <TableCell>{settingValue(setting.default)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {custom.overrides.map((override) => (
        <Box key={override.id} sx={{ mt: 1 }}>
          {override.reason ? <Typography variant="body2"><Box component="span" sx={{ color: 'text.secondary' }}>Why: </Box>{override.reason}</Typography> : null}
          <Typography variant="caption" color="text.secondary">Override {override.id}{override.file ? ` in ${override.file}` : ''}</Typography>
        </Box>
      ))}
    </Box>
  );
}
