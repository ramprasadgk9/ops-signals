{{- define "ops-signals.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "ops-signals.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "ops-signals.labels" -}}
app.kubernetes.io/name: {{ include "ops-signals.name" . }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version | replace "+" "_" }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{/* OPS_SIGNALS_DATABASE_URL from database.urlSecret when a Secret is named, else database.url;
     fails the install when neither is set. */}}
{{- define "ops-signals.databaseUrlEnv" -}}
- name: OPS_SIGNALS_DATABASE_URL
{{- if .Values.database.urlSecret.name }}
  valueFrom:
    secretKeyRef:
      name: {{ .Values.database.urlSecret.name }}
      key: {{ .Values.database.urlSecret.key }}
{{- else if .Values.database.url }}
  value: {{ .Values.database.url | quote }}
{{- else }}
{{- fail "Set database.urlSecret.name to a Secret holding the Postgres URL (see docs/deploy.md#kubernetes-helm), or database.url for a quick test." }}
{{- end }}
{{- end }}

{{/* OPS_SIGNALS_API_TOKEN from security.apiTokenSecret; renders nothing when no Secret is named. */}}
{{- define "ops-signals.apiTokenEnv" -}}
{{- with .Values.security.apiTokenSecret.name }}
- name: OPS_SIGNALS_API_TOKEN
  valueFrom:
    secretKeyRef:
      name: {{ . }}
      key: {{ $.Values.security.apiTokenSecret.key }}
{{- end }}
{{- end }}

{{/* Service account name to use */}}
{{- define "ops-signals.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
    {{ default (include "ops-signals.fullname" .) .Values.serviceAccount.name }}
{{- else -}}
    {{ default "default" .Values.serviceAccount.name }}
{{- end -}}
{{- end }}
