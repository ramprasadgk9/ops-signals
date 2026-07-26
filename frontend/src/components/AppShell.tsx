import type { PropsWithChildren, ReactNode } from 'react';
import {
  Avatar,
  Badge,
  Box,
  Button,
  Chip,
  Divider,
  IconButton,
  InputAdornment,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import HomeRoundedIcon from '@mui/icons-material/HomeRounded';
import TravelExploreRoundedIcon from '@mui/icons-material/TravelExploreRounded';
import CrisisAlertRoundedIcon from '@mui/icons-material/CrisisAlertRounded';
import WorkOutlineRoundedIcon from '@mui/icons-material/WorkOutlineRounded';
import HubRoundedIcon from '@mui/icons-material/HubRounded';
import StorageRoundedIcon from '@mui/icons-material/StorageRounded';
import ChatBubbleOutlineRoundedIcon from '@mui/icons-material/ChatBubbleOutlineRounded';
import ScienceRoundedIcon from '@mui/icons-material/ScienceRounded';
import DatasetRoundedIcon from '@mui/icons-material/DatasetRounded';
import TimelineRoundedIcon from '@mui/icons-material/TimelineRounded';
import SettingsRoundedIcon from '@mui/icons-material/SettingsRounded';
import DnsRoundedIcon from '@mui/icons-material/DnsRounded';
import MenuRoundedIcon from '@mui/icons-material/MenuRounded';
import SearchRoundedIcon from '@mui/icons-material/SearchRounded';
import NotificationsNoneRoundedIcon from '@mui/icons-material/NotificationsNoneRounded';
import HelpOutlineRoundedIcon from '@mui/icons-material/HelpOutlineRounded';
import LightModeRoundedIcon from '@mui/icons-material/LightModeRounded';
import CalendarTodayRoundedIcon from '@mui/icons-material/CalendarTodayRounded';
import AddRoundedIcon from '@mui/icons-material/AddRounded';
import KeyboardArrowDownRoundedIcon from '@mui/icons-material/KeyboardArrowDownRounded';
import ChevronLeftRoundedIcon from '@mui/icons-material/ChevronLeftRounded';
import { Link as RouterLink, useLocation } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/queries';
import { ui } from '../standalone/theme';

type NavItem = {
  label: string;
  to: string;
  icon: ReactNode;
  match?: (pathname: string) => boolean;
  badge?: string;
};

const navItems: NavItem[] = [
  { label: 'Overview', to: '/', icon: <HomeRoundedIcon />, match: (path) => path === '/' },
  { label: 'Investigations', to: '/investigations', icon: <TravelExploreRoundedIcon /> },
  { label: 'Findings', to: '/findings', icon: <CrisisAlertRoundedIcon /> },
  { label: 'Cases', to: '/cases', icon: <WorkOutlineRoundedIcon />, match: (path) => path === '/cases' || path.startsWith('/cases/') },
  { label: 'Behavior Intelligence', to: '/behavior-intelligence', icon: <HubRoundedIcon /> },
  { label: 'Operational Memory', to: '/operational-memory', icon: <StorageRoundedIcon /> },
  { label: 'Ask Ops Signals', to: '/assistant', icon: <ChatBubbleOutlineRoundedIcon />, badge: 'Beta' },
  { label: 'Experiments', to: '/experiments', icon: <ScienceRoundedIcon /> },
  { label: 'Data Sources', to: '/validate-data', icon: <DatasetRoundedIcon /> },
  { label: 'Analyzer Recommendations', to: '/analyzer-recommendation', icon: <TimelineRoundedIcon /> },
];

const systemItems: NavItem[] = [
  { label: 'Settings', to: '/settings', icon: <SettingsRoundedIcon /> },
  { label: 'System', to: '/system', icon: <DnsRoundedIcon /> },
];

function NavButton({ item }: { item: NavItem }) {
  const location = useLocation();
  const active = item.match ? item.match(location.pathname) : location.pathname === item.to;
  return (
    <Button
      component={RouterLink}
      to={item.to}
      startIcon={item.icon}
      fullWidth
      sx={{
        justifyContent: 'flex-start',
        minHeight: 42,
        px: 1.6,
        borderRadius: '8px',
        textTransform: 'none',
        color: active ? ui.red : '#475569',
        bgcolor: active ? 'rgba(255, 77, 87, 0.09)' : 'transparent',
        fontWeight: active ? 800 : 650,
        '& .MuiButton-startIcon': { mr: 1.2, color: active ? ui.red : '#64748b' },
        '&:hover': { bgcolor: active ? 'rgba(255, 77, 87, 0.12)' : '#f8fafc' },
      }}
    >
      <Box component="span" sx={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1, textAlign: 'left' }}>
        {item.label}
      </Box>
      {item.badge ? <Chip label={item.badge} size="small" sx={{ height: 21, fontSize: 11, bgcolor: '#ede9fe', color: ui.purple, fontWeight: 800 }} /> : null}
    </Button>
  );
}

function SystemStatus() {
  const healthQuery = useQuery({ queryKey: ['shell-health'], queryFn: api.health, retry: false });
  const memoryQuery = useQuery({ queryKey: ['shell-memory-health'], queryFn: api.memoryHealth, retry: false });
  const backendHealthy = healthQuery.data?.status === 'ok' || healthQuery.data?.status === 'healthy';
  const memoryHealthy = memoryQuery.data?.status === 'ok' || memoryQuery.data?.status === 'healthy';
  const rows = [
    ['Backend', healthQuery.isError ? 'unavailable' : backendHealthy ? 'healthy' : healthQuery.isLoading ? 'loading' : healthQuery.data?.status ?? 'unknown'],
    ['Database', 'not exposed'],
    ['Qdrant', memoryQuery.isError ? 'unavailable' : memoryHealthy ? 'healthy' : memoryQuery.isLoading ? 'loading' : memoryQuery.data?.status ?? 'unknown'],
    ['MCP Server', 'not exposed'],
  ];
  const overallHealthy = backendHealthy && !memoryQuery.isError;

  return (
    <Box sx={{ mx: 1.5, p: 1.6, borderRadius: '8px', border: `1px solid ${ui.border}`, bgcolor: '#fff' }}>
      <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 1.2 }}>
        <Typography variant="caption" sx={{ fontWeight: 800, color: ui.text }}>
          System Status
        </Typography>
        <Chip label={overallHealthy ? 'Healthy' : 'Partial'} size="small" sx={{ height: 22, bgcolor: overallHealthy ? '#dcfce7' : '#fffbeb', color: overallHealthy ? '#059669' : '#d97706', fontWeight: 800 }} />
      </Stack>
      {rows.map(([item, status]) => (
        <Stack key={item} direction="row" alignItems="center" justifyContent="space-between" sx={{ py: 0.65 }}>
          <Typography variant="caption" sx={{ color: '#64748b', fontWeight: 650 }}>
            {item}
          </Typography>
          <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: status === 'healthy' ? '#22c55e' : status === 'loading' ? '#94a3b8' : '#f59e0b' }} />
        </Stack>
      ))}
    </Box>
  );
}

export function AppShell({ children }: PropsWithChildren) {
  const location = useLocation();
  const isAnalysisPage = location.pathname === '/validate-data';
  return (
    <Box sx={{ minHeight: '100vh', bgcolor: ui.bg, color: ui.text }}>
      <Box
        sx={{
          height: 76,
          px: { xs: 2, lg: 3 },
          borderBottom: `1px solid ${ui.border}`,
          bgcolor: 'rgba(255,255,255,0.92)',
          display: 'grid',
          gridTemplateColumns: { xs: '1fr auto', lg: '290px 1fr auto' },
          alignItems: 'center',
          gap: 2,
          position: 'sticky',
          top: 0,
          zIndex: 20,
          backdropFilter: 'blur(12px)',
        }}
      >
        <Stack direction="row" alignItems="center" spacing={1.5}>
          <Avatar sx={{ width: 42, height: 42, bgcolor: ui.red, fontSize: 15, fontWeight: 900 }}>OS</Avatar>
          <Typography sx={{ fontSize: 20, fontWeight: 900, letterSpacing: 0 }}>Ops Signals</Typography>
          <Tooltip title="Collapse navigation">
            <IconButton sx={{ ml: { xs: 0, lg: 'auto' }, display: { xs: 'none', lg: 'inline-flex' } }}>
              <MenuRoundedIcon />
            </IconButton>
          </Tooltip>
        </Stack>

        <TextField
          size="small"
          placeholder="Search findings, cases, metrics, services..."
          sx={{
            display: { xs: 'none', md: 'block' },
            maxWidth: 580,
            justifySelf: 'center',
            width: '100%',
            '& .MuiOutlinedInput-root': { height: 46, borderRadius: '8px', bgcolor: '#fff' },
          }}
          InputProps={{
            startAdornment: (
              <InputAdornment position="start">
                <SearchRoundedIcon fontSize="small" />
              </InputAdornment>
            ),
            endAdornment: (
              <InputAdornment position="end">
                <Chip label="⌘ K" size="small" sx={{ height: 24, fontWeight: 800, color: '#64748b' }} />
              </InputAdornment>
            ),
          }}
        />

        <Stack direction="row" alignItems="center" spacing={1.2} justifyContent="flex-end">
          {[<NotificationsNoneRoundedIcon />, <HelpOutlineRoundedIcon />, <LightModeRoundedIcon />].map((icon, index) => (
            <IconButton key={index} sx={{ display: { xs: index > 0 ? 'none' : 'inline-flex', sm: 'inline-flex' } }}>
              {index === 0 ? (
                <Badge color="error" badgeContent={1}>
                  {icon}
                </Badge>
              ) : (
                icon
              )}
            </IconButton>
          ))}
          <Avatar sx={{ width: 40, height: 40, bgcolor: '#60a5fa', fontSize: 13, fontWeight: 900 }}>RG</Avatar>
          <KeyboardArrowDownRoundedIcon sx={{ color: '#64748b', display: { xs: 'none', sm: 'block' } }} />
        </Stack>
      </Box>

      <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', lg: '292px 1fr' }, minHeight: 'calc(100vh - 76px)' }}>
        <Box
          component="aside"
          sx={{
            display: { xs: 'none', lg: 'flex' },
            flexDirection: 'column',
            borderRight: `1px solid ${ui.border}`,
            bgcolor: '#fff',
            py: 3,
            minHeight: 'calc(100vh - 76px)',
          }}
        >
          <Stack spacing={0.8} sx={{ px: 1.5 }}>
            {navItems.map((item) => <NavButton key={item.label} item={item} />)}
          </Stack>
          <Divider sx={{ mx: 3, my: 2 }} />
          <Stack spacing={0.8} sx={{ px: 1.5 }}>
            {systemItems.map((item) => <NavButton key={item.label} item={item} />)}
          </Stack>
          <Box sx={{ flex: 1 }} />
          <SystemStatus />
          <Button startIcon={<ChevronLeftRoundedIcon />} sx={{ justifyContent: 'flex-start', mx: 1.5, mt: 6, color: '#475569', textTransform: 'none', fontWeight: 700 }}>
            Collapse
          </Button>
        </Box>

        <Box component="main" sx={{ px: { xs: 2, md: 4 }, py: { xs: 2.5, md: 4 }, overflow: 'hidden' }}>
          <Stack direction="row" justifyContent="flex-end" spacing={1.5} sx={{ display: { xs: 'none', lg: isAnalysisPage ? 'none' : 'flex' }, mb: 3 }}>
            <Button startIcon={<CalendarTodayRoundedIcon />} endIcon={<KeyboardArrowDownRoundedIcon />} variant="outlined" disabled sx={{ height: 44, borderColor: ui.border, color: '#334155', bgcolor: '#fff', textTransform: 'none', fontWeight: 750 }}>
              Time Window Unavailable
            </Button>
            <Button component={RouterLink} to="/validate-data" startIcon={<AddRoundedIcon />} variant="contained" sx={{ height: 44, bgcolor: ui.blue, textTransform: 'none', fontWeight: 850, boxShadow: '0 10px 20px rgba(79,70,229,0.25)' }}>
              New Analysis
            </Button>
          </Stack>
          {children}
        </Box>
      </Box>
    </Box>
  );
}
