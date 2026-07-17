import { AppBar, Box, Button, Toolbar, Typography } from '@mui/material';
import DashboardRoundedIcon from '@mui/icons-material/DashboardRounded';
import HistoryRoundedIcon from '@mui/icons-material/HistoryRounded';
import StarOutlineRoundedIcon from '@mui/icons-material/StarOutlineRounded';
import PsychologyAltRoundedIcon from '@mui/icons-material/PsychologyAltRounded';
import AutoGraphRoundedIcon from '@mui/icons-material/AutoGraphRounded';
import SettingsRoundedIcon from '@mui/icons-material/SettingsRounded';
import DarkModeRoundedIcon from '@mui/icons-material/DarkModeRounded';
import LightModeRoundedIcon from '@mui/icons-material/LightModeRounded';
import { Link as RouterLink, useLocation } from 'react-router-dom';
import { useColorMode } from '../theme/ThemeProviderWithMode';

export function TopNavigation() {
  const { mode, toggle } = useColorMode();
  const location = useLocation();

  const isActive = (path: string) => location.pathname === path;

  const navButtonSx = {
    borderRadius: 999,
    px: 1.4,
    gap: 0.75,
    textTransform: 'none',
    fontWeight: 600,
  };

  return (
    <AppBar position="sticky" color="transparent" elevation={0} sx={{ backdropFilter: 'blur(12px)' }}>
      <Toolbar sx={{ display: 'flex', justifyContent: 'space-between' }}>
        <Typography variant="h5" component={RouterLink} to="/" sx={{ textDecoration: 'none', color: 'inherit', cursor: 'pointer' }}>
          Ops Intelligence
        </Typography>
        <Box sx={{ display: 'flex', gap: 0.5 }}>
          <Button 
            component={RouterLink} 
            to="/"
            variant={isActive('/') ? 'contained' : 'text'}
            size="small"
            startIcon={<DashboardRoundedIcon />}
            sx={navButtonSx}
          >
            Overview
          </Button>
          <Button 
            component={RouterLink} 
            to="/history"
            variant={isActive('/history') ? 'contained' : 'text'}
            size="small"
            startIcon={<HistoryRoundedIcon />}
            sx={navButtonSx}
          >
            History
          </Button>
          <Button 
            component={RouterLink} 
            to="/capabilities"
            variant={isActive('/capabilities') ? 'contained' : 'text'}
            size="small"
            startIcon={<StarOutlineRoundedIcon />}
            sx={navButtonSx}
          >
            Capabilities
          </Button>
          <Button
            component={RouterLink}
            to="/behavior-intelligence"
            variant={isActive('/behavior-intelligence') ? 'contained' : 'text'}
            size="small"
            startIcon={<PsychologyAltRoundedIcon />}
            sx={navButtonSx}
          >
            Behavior
          </Button>
          <Button
            component={RouterLink}
            to="/analyzer-recommendation"
            variant={isActive('/analyzer-recommendation') ? 'contained' : 'text'}
            size="small"
            startIcon={<AutoGraphRoundedIcon />}
            sx={navButtonSx}
          >
            Analyzer Rec
          </Button>
          <Button 
            component={RouterLink} 
            to="/settings"
            variant={isActive('/settings') ? 'contained' : 'text'}
            size="small"
            startIcon={<SettingsRoundedIcon />}
            sx={navButtonSx}
          >
            Settings
          </Button>
          <Button
            onClick={toggle}
            size="small"
            startIcon={mode === 'light' ? <DarkModeRoundedIcon /> : <LightModeRoundedIcon />}
            sx={navButtonSx}
          >
            {mode === 'light' ? 'Dark' : 'Light'}
          </Button>
        </Box>
      </Toolbar>
    </AppBar>
  );
}
