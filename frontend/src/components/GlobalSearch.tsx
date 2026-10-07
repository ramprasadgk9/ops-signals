import { useEffect, useRef, useState } from 'react';
import { Autocomplete, Box, Chip, InputAdornment, TextField, Typography } from '@mui/material';
import SearchRoundedIcon from '@mui/icons-material/SearchRounded';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/queries';
import { findingLevel } from '../utils/findingLevel';
import type { Finding } from '../types';

const DEBOUNCE_MS = 250;
const MIN_QUERY_LENGTH = 2;

export function GlobalSearch() {
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);
  const [inputValue, setInputValue] = useState('');
  const [debouncedQuery, setDebouncedQuery] = useState('');

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedQuery(inputValue.trim()), DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [inputValue]);

  useEffect(() => {
    function handleKeydown(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        inputRef.current?.focus();
      }
    }
    window.addEventListener('keydown', handleKeydown);
    return () => window.removeEventListener('keydown', handleKeydown);
  }, []);

  const searchQuery = useQuery({
    queryKey: ['global-search', debouncedQuery],
    queryFn: () => api.findingsSearch({ q: debouncedQuery, window: '7d', limit: 8 }),
    enabled: debouncedQuery.length >= MIN_QUERY_LENGTH,
  });

  const options = debouncedQuery.length >= MIN_QUERY_LENGTH ? (searchQuery.data ?? []) : [];

  return (
    <Autocomplete<Finding, false, false, true>
      freeSolo
      // Without freeSolo, Autocomplete treats `value` (the selected option) as the source of
      // truth for `inputValue` and resyncs the input back to it after every keystroke - since
      // nothing is ever "selected" here until a result is clicked, that reset the input to empty
      // on every character typed. freeSolo turns that resync off; getOptionLabel below still
      // keeps result rows/selection working the same as a normal (non-free-text) Autocomplete.
      size="small"
      sx={{ display: { xs: 'none', md: 'block' }, maxWidth: 580, justifySelf: 'center', width: '100%' }}
      options={options}
      filterOptions={(items) => items} // results already filtered server-side (GET /api/findings/search)
      loading={searchQuery.isFetching}
      inputValue={inputValue}
      onInputChange={(_, value) => setInputValue(value)}
      getOptionLabel={(finding) => (typeof finding === 'string' ? finding : `${finding.service ?? 'unknown'} / ${finding.metric_name}`)}
      isOptionEqualToValue={(a, b) => a.id === b.id}
      noOptionsText={debouncedQuery.length >= MIN_QUERY_LENGTH ? 'No matching findings' : 'Type to search findings, cases, metrics, services'}
      onChange={(_, selected) => {
        // Only an actual result selection navigates - freeSolo also allows Enter on free text,
        // which arrives here as a plain string and should be ignored (nothing to navigate to).
        if (selected && typeof selected === 'object') {
          setInputValue('');
          setDebouncedQuery('');
          navigate('/findings');
        }
      }}
      renderOption={(props, finding) => {
        const level = findingLevel(finding.health_status);
        return (
          <Box component="li" {...props} key={finding.id ?? `${finding.service}-${finding.metric_name}`}>
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.25, py: 0.25, width: '100%' }}>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                <Typography variant="body2" sx={{ fontWeight: 700 }}>
                  {finding.service ?? 'unknown'} / {finding.metric_name}
                </Typography>
                <Chip size="small" label={level.label} sx={{ color: level.tone.color, bgcolor: level.tone.bg, height: 20, fontSize: 11, fontWeight: 800 }} />
              </Box>
              <Typography variant="caption" color="text.secondary">
                {finding.title}
              </Typography>
            </Box>
          </Box>
        );
      }}
      renderInput={(params) => (
        <TextField
          {...params}
          inputRef={inputRef}
          placeholder="Search findings, cases, metrics, services..."
          sx={{ '& .MuiOutlinedInput-root': { height: 46, borderRadius: '8px', bgcolor: '#fff', paddingTop: '0 !important', paddingBottom: '0 !important' } }}
          InputProps={{
            ...params.InputProps,
            startAdornment: (
              <InputAdornment position="start">
                <SearchRoundedIcon fontSize="small" />
              </InputAdornment>
            ),
            endAdornment: (
              <>
                {!inputValue && <Chip label="⌘ K" size="small" sx={{ height: 24, fontWeight: 800, color: '#64748b', mr: 1 }} />}
                {params.InputProps.endAdornment}
              </>
            ),
          }}
        />
      )}
    />
  );
}
