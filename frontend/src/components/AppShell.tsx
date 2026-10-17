import { useEffect, useState } from 'react';
import type { PropsWithChildren, ReactNode } from 'react';
import {
  Avatar,
  Badge,
  Box,
  Button,
  Chip,
  Divider,
  IconButton,
  Stack,
  Tooltip,
  Typography,
} from '@mui/material';
import HomeRoundedIcon from '@mui/icons-material/HomeRounded';
import InputRoundedIcon from '@mui/icons-material/InputRounded';
import PersonRoundedIcon from '@mui/icons-material/PersonRounded';
import AutoModeRoundedIcon from '@mui/icons-material/AutoModeRounded';
import TravelExploreRoundedIcon from '@mui/icons-material/TravelExploreRounded';
import VisibilityOutlinedIcon from '@mui/icons-material/VisibilityOutlined';
import CrisisAlertRoundedIcon from '@mui/icons-material/CrisisAlertRounded';
import WorkOutlineRoundedIcon from '@mui/icons-material/WorkOutlineRounded';
import HubRoundedIcon from '@mui/icons-material/HubRounded';
import StorageRoundedIcon from '@mui/icons-material/StorageRounded';
import ChatBubbleOutlineRoundedIcon from '@mui/icons-material/ChatBubbleOutlineRounded';
import ScienceRoundedIcon from '@mui/icons-material/ScienceRounded';
import TimelineRoundedIcon from '@mui/icons-material/TimelineRounded';
import SettingsRoundedIcon from '@mui/icons-material/SettingsRounded';
import DnsRoundedIcon from '@mui/icons-material/DnsRounded';
import MenuRoundedIcon from '@mui/icons-material/MenuRounded';
import NotificationsNoneRoundedIcon from '@mui/icons-material/NotificationsNoneRounded';
import NotificationsActiveOutlinedIcon from '@mui/icons-material/NotificationsActiveOutlined';
import HelpOutlineRoundedIcon from '@mui/icons-material/HelpOutlineRounded';
import LightModeRoundedIcon from '@mui/icons-material/LightModeRounded';
import { GlobalSearch } from './GlobalSearch';
import CalendarTodayRoundedIcon from '@mui/icons-material/CalendarTodayRounded';
import AddRoundedIcon from '@mui/icons-material/AddRounded';
import KeyboardArrowDownRoundedIcon from '@mui/icons-material/KeyboardArrowDownRounded';
import ChevronLeftRoundedIcon from '@mui/icons-material/ChevronLeftRounded';
import { Link as RouterLink, useLocation } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/queries';
import { useFeatureAvailability } from '../hooks/useFeatureAvailability';
import { ui } from '../standalone/theme';
import { showAllNavFeatures, useHiddenNavFeatures } from '../utils/hiddenNavFeatures';

type NavItem = {
  label: string;
  to: string;
  icon: ReactNode;
  match?: (pathname: string) => boolean;
  badge?: string;
  /** Feature id (backend/app/capabilities/availability.py) the page needs a source for. While it
   * is off, the item moves to the "More with Prometheus / Grafana" group. */
  feature?: string;
};

const navItems: NavItem[] = [
  { label: 'Overview', to: '/', icon: <HomeRoundedIcon />, match: (path) => path === '/' },
  { label: 'Alerts', to: '/alerts', icon: <NotificationsActiveOutlinedIcon />, feature: 'alert_enrichment' },
  { label: 'Integrations', to: '/integrations', icon: <InputRoundedIcon /> },
  { label: 'Autonomous Analysis Configure', to: '/autonomous-monitoring', icon: <AutoModeRoundedIcon />, feature: 'autonomous_analysis' },
  { label: 'Investigations', to: '/investigations', icon: <TravelExploreRoundedIcon /> },
  { label: 'Findings', to: '/findings', icon: <CrisisAlertRoundedIcon /> },
  { label: 'Metric Usage', to: '/metric-usage', icon: <VisibilityOutlinedIcon />, feature: 'metric_usage' },
  { label: 'Cases', to: '/cases', icon: <WorkOutlineRoundedIcon />, match: (path) => path === '/cases' || path.startsWith('/cases/') },
  { label: 'Behavior Intelligence', to: '/behavior-intelligence', icon: <HubRoundedIcon /> },
  { label: 'Behavior Lab', to: '/behavior-intelligence/lab', icon: <ScienceRoundedIcon /> },
  { label: 'Operational Memory', to: '/operational-memory', icon: <StorageRoundedIcon /> },
  { label: 'Ask Ops Signals', to: '/assistant', icon: <ChatBubbleOutlineRoundedIcon />, badge: 'Beta' },
  { label: 'New Analysis', to: '/validate-data', icon: <AddRoundedIcon /> },
];

const analyzerLabItems: NavItem[] = [
  { label: 'Z-Score Anomaly Lab', to: '/experiments/zscore-anomaly-lab', icon: <ScienceRoundedIcon /> },
  { label: 'PyOD Outlier Lab', to: '/experiments/pyod-outlier-lab', icon: <ScienceRoundedIcon /> },
  { label: 'Prophet Forecast Lab', to: '/experiments/prophet-forecast-lab', icon: <TimelineRoundedIcon /> },
  { label: 'Ruptures Change Point Lab', to: '/experiments/ruptures-change-point-lab', icon: <TimelineRoundedIcon /> },
  { label: 'STUMPY Motif Lab', to: '/experiments/stumpy-motif-lab', icon: <TimelineRoundedIcon /> },
  { label: 'Trend Lab', to: '/experiments/trend-lab', icon: <TimelineRoundedIcon /> },
];

const analyzerWorkbenchItems: NavItem[] = [
  { label: 'Add Analyzer', to: '/experiments/add-analyzer', icon: <AddRoundedIcon /> },
  { label: 'Recommendations', to: '/analyzer-recommendation', icon: <TimelineRoundedIcon /> },
];

const systemItems: NavItem[] = [
  { label: 'Settings', to: '/settings', icon: <SettingsRoundedIcon /> },
  { label: 'System', to: '/system', icon: <DnsRoundedIcon /> },
];

function NavButton({ item, nested = false, needsSource = false }: { item: NavItem; nested?: boolean; needsSource?: boolean }) {
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
        minHeight: nested ? 36 : 42,
        px: nested ? 1.2 : 1.6,
        ml: nested ? 2.2 : 0,
        width: nested ? 'calc(100% - 17.6px)' : '100%',
        borderRadius: '8px',
        textTransform: 'none',
        color: active ? ui.red : 'var(--os-text-2)',
        bgcolor: active ? 'rgba(255, 77, 87, 0.09)' : 'transparent',
        fontWeight: active ? 800 : nested ? 600 : 650,
        fontSize: nested ? 13 : 14,
        '& .MuiButton-startIcon': { mr: 1.1, color: active ? ui.red : 'var(--os-muted)', '& svg': { fontSize: nested ? 18 : 20 } },
        '&:hover': { bgcolor: active ? 'rgba(255, 77, 87, 0.12)' : 'var(--os-surface-alt)' },
      }}
    >
      <Box component="span" title={item.label} sx={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1, textAlign: 'left' }}>
        {item.label}
      </Box>
      {item.badge ? <Chip label={item.badge} size="small" sx={{ height: 21, fontSize: 11, bgcolor: 'var(--os-tint-violet)', color: ui.purple, fontWeight: 800 }} /> : null}
      {needsSource ? <Chip label="Connect" size="small" sx={{ height: 21, fontSize: 11, bgcolor: 'var(--os-tint-amber)', color: 'var(--os-ink-amber)', fontWeight: 800 }} /> : null}
    </Button>
  );
}

function WorkbenchButton({
  label,
  icon,
  active,
  onClick,
  expanded,
  to,
  activeColor = 'var(--os-ink-brand)',
  activeBg = 'rgba(15, 118, 110, 0.09)',
  inactiveColor = 'var(--os-ink-brand)',
}: {
  label: string;
  icon: ReactNode;
  active: boolean;
  onClick?: () => void;
  expanded?: boolean;
  to?: string;
  activeColor?: string;
  activeBg?: string;
  inactiveColor?: string;
}) {
  const commonSx = {
    justifyContent: 'flex-start',
    minHeight: 42,
    px: 1.6,
    borderRadius: '8px',
    textTransform: 'none',
    color: active ? activeColor : inactiveColor,
    bgcolor: active ? activeBg : 'transparent',
    fontWeight: active ? 800 : 750,
    fontSize: 14,
    '&:hover': { bgcolor: active ? activeBg : 'var(--os-surface-alt)' },
  };
  const content = (
    <>
      <Box sx={{ width: 24, minWidth: 24, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', mr: 1.1, color: active ? activeColor : inactiveColor, '& svg': { fontSize: 20 } }}>
        {icon}
      </Box>
      <Box component="span" sx={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1, textAlign: 'left' }}>
        {label}
      </Box>
      {expanded !== undefined ? <KeyboardArrowDownRoundedIcon sx={{ color: active ? activeColor : inactiveColor, transform: expanded ? 'rotate(180deg)' : 'rotate(0deg)', transition: 'transform 160ms ease' }} /> : null}
    </>
  );

  if (to) {
    return (
      <Button component={RouterLink} to={to} fullWidth sx={commonSx}>
        {content}
      </Button>
    );
  }

  return (
    <Button onClick={onClick} fullWidth sx={commonSx}>
      {content}
    </Button>
  );
}

/** Pages whose feature the connected sources can't run yet: kept findable, not mixed in with the
 * ones that work. A viewer can hide an item from here and bring it back. */
function NeedsSourceGroup({ items }: { items: NavItem[] }) {
  const hidden = useHiddenNavFeatures();
  if (!items.length) return null;
  const shown = items.filter((item) => !hidden.includes(item.feature ?? ''));
  const hiddenCount = items.length - shown.length;
  return (
    <Box data-testid="nav-needs-source" sx={{ pt: 1.4 }}>
      <Typography sx={{ px: 1.6, pb: 0.6, fontSize: 12, fontWeight: 850, letterSpacing: 0.8, textTransform: 'uppercase', color: 'var(--os-muted)' }}>
        More with Prometheus / Grafana
      </Typography>
      <Stack spacing={0.8}>
        {shown.map((item) => <NavButton key={item.label} item={item} needsSource />)}
      </Stack>
      {hiddenCount ? (
        <Button onClick={showAllNavFeatures} size="small" sx={{ ml: 1, textTransform: 'none', fontWeight: 700, color: 'var(--os-muted)' }}>
          Show {hiddenCount} hidden
        </Button>
      ) : null}
    </Box>
  );
}

function SystemStatus() {
  const healthQuery = useQuery({ queryKey: ['shell-health'], queryFn: api.health, retry: false });
  const memoryQuery = useQuery({ queryKey: ['shell-memory-health'], queryFn: api.memoryHealth, retry: false });
  // A 503 from /api/health still has a body: the backend is up and only the database is down.
  const backendHealthy = Boolean(healthQuery.data);
  const database = healthQuery.data?.database;
  const memoryHealthy = memoryQuery.data?.status === 'ok' || memoryQuery.data?.status === 'healthy';
  const rows = [
    ['Backend', healthQuery.isError ? 'unavailable' : backendHealthy ? 'healthy' : healthQuery.isLoading ? 'loading' : healthQuery.data?.status ?? 'unknown'],
    ['Database', healthQuery.isError ? 'unknown' : database === 'ok' ? 'healthy' : healthQuery.isLoading ? 'loading' : database ?? 'unknown'],
    ['Qdrant', memoryQuery.isError ? 'unavailable' : memoryHealthy ? 'healthy' : memoryQuery.isLoading ? 'loading' : memoryQuery.data?.status ?? 'unknown'],
    ['MCP Server', 'not exposed'],
  ];
  const overallHealthy = backendHealthy && !memoryQuery.isError;

  return (
    <Box sx={{ mx: 1.5, p: 1.6, borderRadius: '8px', border: `1px solid ${ui.border}`, bgcolor: 'var(--os-surface)' }}>
      <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 1.2 }}>
        <Typography variant="caption" sx={{ fontWeight: 800, color: ui.text }}>
          System Status
        </Typography>
        <Chip label={overallHealthy ? 'Healthy' : 'Partial'} size="small" sx={{ height: 22, bgcolor: overallHealthy ? 'var(--os-tint-green)' : 'var(--os-tint-amber)', color: overallHealthy ? '#059669' : '#d97706', fontWeight: 800 }} />
      </Stack>
      {rows.map(([item, status]) => (
        <Stack key={item} direction="row" alignItems="center" justifyContent="space-between" sx={{ py: 0.65 }}>
          <Typography variant="caption" sx={{ color: 'var(--os-muted)', fontWeight: 650 }}>
            {item}
          </Typography>
          <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: status === 'healthy' ? '#22c55e' : status === 'loading' ? 'var(--os-muted)' : '#f59e0b' }} />
        </Stack>
      ))}
    </Box>
  );
}

export function AppShell({ children }: PropsWithChildren) {
  const location = useLocation();
  const isAnalysisPage = location.pathname === '/validate-data';
  const isAnalyzerWorkbenchPage =
    analyzerLabItems.some((item) => location.pathname === item.to) ||
    analyzerWorkbenchItems.some((item) => location.pathname === item.to);
  const [analyzerWorkbenchOpen, setAnalyzerWorkbenchOpen] = useState(isAnalyzerWorkbenchPage);
  const [labsOpen, setLabsOpen] = useState(isAnalyzerWorkbenchPage);
  const { isOff } = useFeatureAvailability();
  const needsSourceItems = navItems.filter((item) => item.feature && isOff(item.feature));
  const mainItems = navItems.filter((item) => !needsSourceItems.includes(item));
  useEffect(() => {
    if (isAnalyzerWorkbenchPage) setAnalyzerWorkbenchOpen(true);
  }, [isAnalyzerWorkbenchPage, location.pathname]);
  return (
    <Box sx={{ minHeight: '100vh', bgcolor: ui.bg, color: ui.text }}>
      <Box
        sx={{
          height: 76,
          px: { xs: 2, lg: 3 },
          borderBottom: `1px solid ${ui.border}`,
          bgcolor: 'var(--os-header-bg)',
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
            <IconButton aria-label="Collapse navigation" sx={{ ml: { xs: 0, lg: 'auto' }, display: { xs: 'none', lg: 'inline-flex' } }}>
              <MenuRoundedIcon />
            </IconButton>
          </Tooltip>
        </Stack>

        <GlobalSearch />

        <Stack direction="row" alignItems="center" spacing={1.2} justifyContent="flex-end">
          {[<NotificationsNoneRoundedIcon />, <HelpOutlineRoundedIcon />, <LightModeRoundedIcon />].map((icon, index) => (
            <IconButton key={index} aria-label={['Notifications', 'Help', 'Theme'][index]} sx={{ display: { xs: index > 0 ? 'none' : 'inline-flex', sm: 'inline-flex' } }}>
              {index === 0 ? (
                <Badge color="error" badgeContent={1}>
                  {icon}
                </Badge>
              ) : (
                icon
              )}
            </IconButton>
          ))}
          <Avatar sx={{ width: 40, height: 40, bgcolor: '#60a5fa' }}>
            <PersonRoundedIcon />
          </Avatar>
          <KeyboardArrowDownRoundedIcon sx={{ color: 'var(--os-muted)', display: { xs: 'none', sm: 'block' } }} />
        </Stack>
      </Box>

      <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', lg: '292px 1fr' }, minHeight: 'calc(100vh - 76px)' }}>
        <Box
          component="aside"
          sx={{
            display: { xs: 'none', lg: 'flex' },
            flexDirection: 'column',
            borderRight: `1px solid ${ui.border}`,
            bgcolor: 'var(--os-surface)',
            py: 3,
            minHeight: 'calc(100vh - 76px)',
          }}
        >
          <Stack spacing={0.8} sx={{ px: 1.5 }}>
            {mainItems.map((item) => <NavButton key={item.label} item={item} />)}
            <NeedsSourceGroup items={needsSourceItems} />
            <Button
              onClick={() => setAnalyzerWorkbenchOpen((open) => !open)}
              endIcon={<KeyboardArrowDownRoundedIcon sx={{ transform: analyzerWorkbenchOpen ? 'rotate(180deg)' : 'rotate(0deg)', transition: 'transform 160ms ease' }} />}
              fullWidth
              sx={{
                justifyContent: 'space-between',
                minHeight: 34,
                px: 1.6,
                pt: 1.4,
                color: ui.red,
                textTransform: 'uppercase',
                letterSpacing: 1.2,
                fontSize: 14,
                fontWeight: 900,
                '& .MuiButton-endIcon svg': { color: ui.red, fontSize: 22 },
                '&:hover': { bgcolor: 'rgba(255, 77, 87, 0.05)' },
              }}
            >
              Analyzer Workbench
            </Button>
            {analyzerWorkbenchOpen ? (
              <>
                <WorkbenchButton
                  label="Labs"
                  icon={<ScienceRoundedIcon />}
                  active={analyzerLabItems.some((item) => location.pathname === item.to)}
                  onClick={() => setLabsOpen((open) => !open)}
                  expanded={labsOpen}
                />
                {labsOpen ? analyzerLabItems.map((item) => <NavButton key={item.label} item={item} nested />) : null}
                {analyzerWorkbenchItems.map((item) => (
                  <WorkbenchButton
                    key={item.label}
                    label={item.label}
                    icon={item.icon}
                    to={item.to}
                    active={item.match ? item.match(location.pathname) : location.pathname === item.to}
                  />
                ))}
              </>
            ) : null}
          </Stack>
          <Divider sx={{ mx: 3, my: 2 }} />
          <Stack spacing={0.8} sx={{ px: 1.5 }}>
            {systemItems.map((item) => <NavButton key={item.label} item={item} />)}
          </Stack>
          <Box sx={{ flex: 1 }} />
          <SystemStatus />
          <Button startIcon={<ChevronLeftRoundedIcon />} sx={{ justifyContent: 'flex-start', mx: 1.5, mt: 6, color: 'var(--os-text-2)', textTransform: 'none', fontWeight: 700 }}>
            Collapse
          </Button>
        </Box>

        <Box component="main" sx={{ px: { xs: 2, md: 4 }, py: { xs: 2.5, md: 4 }, minWidth: 0, overflowX: 'auto' }}>
          <Stack direction="row" justifyContent="flex-end" spacing={1.5} sx={{ display: { xs: 'none', lg: isAnalysisPage ? 'none' : 'flex' }, mb: 3 }}>
            <Button startIcon={<CalendarTodayRoundedIcon />} endIcon={<KeyboardArrowDownRoundedIcon />} variant="outlined" disabled sx={{ height: 44, borderColor: ui.border, color: 'var(--os-text-2)', bgcolor: 'var(--os-surface)', textTransform: 'none', fontWeight: 750 }}>
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
