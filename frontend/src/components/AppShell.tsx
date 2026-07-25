import { Box, Button, Chip, Stack, Typography } from '@mui/material';
import DashboardRoundedIcon from '@mui/icons-material/DashboardRounded';
import TrendingUpRoundedIcon from '@mui/icons-material/TrendingUpRounded';
import FactCheckRoundedIcon from '@mui/icons-material/FactCheckRounded';
import ScienceRoundedIcon from '@mui/icons-material/ScienceRounded';
import InsightsRoundedIcon from '@mui/icons-material/InsightsRounded';
import TuneRoundedIcon from '@mui/icons-material/TuneRounded';
import StorageRoundedIcon from '@mui/icons-material/StorageRounded';
import SettingsRoundedIcon from '@mui/icons-material/SettingsRounded';
import type { PropsWithChildren } from 'react';
import { Link as RouterLink, useLocation } from 'react-router-dom';
import { TopNavigation } from './TopNavigation';

export function AppShell({ children }: PropsWithChildren) {
  const location = useLocation();
  const navItemSx = (active: boolean) => ({
    justifyContent: 'flex-start',
    textTransform: 'none',
    borderRadius: 2.5,
    px: 2,
    py: 1.15,
    fontWeight: active ? 700 : 600,
    color: active ? '#ef4444' : '#334155',
    background: active ? 'rgba(239, 68, 68, 0.08)' : 'transparent',
    '& .MuiButton-startIcon': { mr: 1.25 },
  });

  return (
    <Box
      sx={{
        minHeight: '100vh',
        background:
          'linear-gradient(180deg, rgba(243, 246, 253, 0.96) 0%, rgba(248, 250, 252, 1) 28%, rgba(241, 245, 249, 1) 100%)',
      }}
    >
      <TopNavigation />
      <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', lg: '240px 1fr' }, minHeight: 'calc(100vh - 76px)' }}>
        <Box
          sx={{
            borderRight: '1px solid rgba(15, 23, 42, 0.08)',
            background: 'rgba(255,255,255,0.78)',
            px: 1.5,
            py: 2.25,
            display: { xs: 'none', lg: 'block' },
          }}
        >
          <Stack spacing={1.1}>
            <Button component={RouterLink} to="/" startIcon={<DashboardRoundedIcon />} sx={navItemSx(location.pathname === '/')}>
              Overview
            </Button>
            <Typography variant="overline" color="text.secondary" sx={{ px: 2, pt: 1 }}>
              Analysis
            </Typography>
            <Button component={RouterLink} to="/" startIcon={<TrendingUpRoundedIcon />} sx={navItemSx(location.pathname === '/')}>
              Analyses
            </Button>
            <Button component={RouterLink} to="/findings" startIcon={<FactCheckRoundedIcon />} sx={navItemSx(location.pathname === '/findings')}>
              Findings
            </Button>
            <Button component={RouterLink} to="/cases/1" startIcon={<ScienceRoundedIcon />} sx={navItemSx(location.pathname.startsWith('/cases'))}>
              Cases
            </Button>
            <Button component={RouterLink} to="/signals/1" startIcon={<InsightsRoundedIcon />} sx={navItemSx(location.pathname.startsWith('/signals'))}>
              Signals
            </Button>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, px: 2, pt: 1 }}>
              <Typography variant="overline" color="text.secondary">
                Behavior Rules
              </Typography>
              <Chip label="Beta" size="small" sx={{ height: 22, fontSize: 11 }} />
            </Box>
            <Button component={RouterLink} to="/behavior-intelligence" startIcon={<TuneRoundedIcon />} sx={navItemSx(location.pathname === '/behavior-intelligence')}>
              Behavior Rules
            </Button>
            <Typography variant="overline" color="text.secondary" sx={{ px: 2, pt: 1 }}>
              Data
            </Typography>
            <Button component={RouterLink} to="/validate-data" startIcon={<StorageRoundedIcon />} sx={navItemSx(location.pathname === '/validate-data')}>
              Data Sources
            </Button>
            <Typography variant="overline" color="text.secondary" sx={{ px: 2, pt: 1 }}>
              System
            </Typography>
            <Button component={RouterLink} to="/settings" startIcon={<SettingsRoundedIcon />} sx={navItemSx(location.pathname === '/settings')}>
              Settings
            </Button>
          </Stack>
        </Box>
        <Box sx={{ px: { xs: 2, lg: 3 }, py: { xs: 2, lg: 3 } }}>{children}</Box>
      </Box>
    </Box>
  );
}
