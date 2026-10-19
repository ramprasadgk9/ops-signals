import React from 'react';
import { useState } from 'react';
import { getApiToken, setApiToken } from './backendClient';
import { Field, styles } from './plainUi';

// The optional OPS_SIGNALS_API_TOKEN, kept in this browser's storage (see backendClient).
export function ApiTokenField({ onSaved }: { onSaved?: () => void }) {
  const [token, setToken] = useState(getApiToken);
  return (
    <Field label="API token (optional)">
      <input
        style={styles.input}
        type="password"
        autoComplete="off"
        value={token}
        placeholder="Only if the backend requires one"
        onChange={(event) => setToken(event.target.value)}
        onBlur={() => {
          setApiToken(token);
          onSaved?.();
        }}
      />
    </Field>
  );
}
