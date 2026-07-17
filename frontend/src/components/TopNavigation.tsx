import { AppBar, Box, Button, Toolbar, Typography } from '@mui/material';
import { Link as RouterLink, useLocation } from 'react-router-dom';
import { useColorMode } from '../theme/ThemeProviderWithMode';

export function TopNavigation() {
  const { mode, toggle } = useColorMode();
  const location = useLocation();

  const isActive = (path: string) => location.pathname === path;

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
          >
            Overview
          </Button>
          <Button 
            component={RouterLink} 
            to="/history"
            variant={isActive('/history') ? 'contained' : 'text'}
            size="small"
          >
            History
          </Button>
          <Button 
            component={RouterLink} 
            to="/capabilities"
            variant={isActive('/capabilities') ? 'contained' : 'text'}
            size="small"
          >
            Capabilities
          </Button>
          <Button
            component={RouterLink}
            to="/behavior-intelligence"
            variant={isActive('/behavior-intelligence') ? 'contained' : 'text'}
            size="small"
          >
            Behavior
          </Button>
          <Button
            component={RouterLink}
            to="/analyzer-recommendation"
            variant={isActive('/analyzer-recommendation') ? 'contained' : 'text'}
            size="small"
          >
            Analyzer Rec
          </Button>
          <Button 
            component={RouterLink} 
            to="/settings"
            variant={isActive('/settings') ? 'contained' : 'text'}
            size="small"
          >
            Settings
          </Button>
          <Button onClick={toggle} size="small">{mode === 'light' ? 'Dark' : 'Light'}</Button>
        </Box>
      </Toolbar>
    </AppBar>
  );
}
