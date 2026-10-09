import { AppBar, Box, IconButton, InputBase, Toolbar, Typography } from '@mui/material';
import MenuRoundedIcon from '@mui/icons-material/MenuRounded';
import SearchRoundedIcon from '@mui/icons-material/SearchRounded';
import NotificationsNoneRoundedIcon from '@mui/icons-material/NotificationsNoneRounded';
import DarkModeRoundedIcon from '@mui/icons-material/DarkModeRounded';
import LightModeRoundedIcon from '@mui/icons-material/LightModeRounded';
import { useColorMode } from '../theme/ThemeProviderWithMode';

export function TopNavigation() {
  const { mode, toggle } = useColorMode();

  return (
    <AppBar
      position="sticky"
      color="transparent"
      elevation={0}
      sx={{
        backdropFilter: 'blur(16px)',
        borderBottom: '1px solid rgba(15, 23, 42, 0.08)',
        background: 'rgba(255,255,255,0.82)',
      }}
    >
      <Toolbar sx={{ display: 'flex', justifyContent: 'space-between', gap: 2, minHeight: 76 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
            <Box sx={{ width: 34, height: 34, borderRadius: '50%', background: 'linear-gradient(135deg, #ef4444, #fb7185)', display: 'grid', placeItems: 'center', color: '#fff', fontWeight: 800 }}>OS</Box>
            <Typography variant="h6" sx={{ fontWeight: 800 }}>
              Ops Signals
            </Typography>
          </Box>
          <IconButton size="small" sx={{ ml: 1 }}>
            <MenuRoundedIcon />
          </IconButton>
          <Typography variant="body2" color="text.secondary">
            Analyses
          </Typography>
          <Typography variant="body2" color="text.secondary">
            /
          </Typography>
          <Typography variant="body2" sx={{ fontWeight: 600 }}>
            cpu_usage - 7/24/2026
          </Typography>
        </Box>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
          <Box
            sx={{
              display: 'flex',
              alignItems: 'center',
              gap: 1,
              px: 1.5,
              py: 0.75,
              borderRadius: 999,
              border: '1px solid rgba(15, 23, 42, 0.08)',
              background: 'var(--os-surface)',
              minWidth: 260,
            }}
          >
            <SearchRoundedIcon fontSize="small" color="action" />
            <InputBase placeholder="Search..." sx={{ flex: 1, fontSize: 14 }} />
            <Typography variant="caption" sx={{ px: 0.75, py: 0.25, borderRadius: 1, background: 'rgba(15,23,42,0.05)' }}>
              ⌘K
            </Typography>
          </Box>
          <IconButton size="small">
            <NotificationsNoneRoundedIcon />
          </IconButton>
          <Box
            sx={{
              width: 28,
              height: 28,
              borderRadius: '50%',
              display: 'grid',
              placeItems: 'center',
              bgcolor: 'error.main',
              color: '#fff',
              fontSize: 12,
              fontWeight: 700,
              position: 'relative',
            }}
          >
            3
          </Box>
          <IconButton size="small" onClick={toggle}>
            {mode === 'light' ? <DarkModeRoundedIcon /> : <LightModeRoundedIcon />}
          </IconButton>
          <Box
            sx={{
              width: 36,
              height: 36,
              borderRadius: '50%',
              display: 'grid',
              placeItems: 'center',
              background: 'linear-gradient(135deg, #93c5fd, #60a5fa)',
              color: '#fff',
              fontWeight: 700,
              fontSize: 14,
            }}
          >
            RG
          </Box>
        </Box>
      </Toolbar>
    </AppBar>
  );
}
